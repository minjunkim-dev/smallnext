use axum::http::StatusCode;
use sqlx::{PgPool, Postgres, Transaction};

pub(super) struct Reservation {
    // A transaction-scoped advisory lock disappears on connection loss/rollback.
    // No per-request identity is written to PostgreSQL.
    _active: Transaction<'static, Postgres>,
    month: String,
    day: String,
    amount: i64,
    pub(super) metric: i64,
}

#[derive(Clone, Copy)]
pub(super) struct Limits {
    pub month: i64,
    pub day: i64,
    pub user_requests: i64,
}

pub(super) async fn reserve(
    pool: &PgPool,
    uid: &str,
    user_hash: &[u8],
    kind: &str,
    amount: i64,
    limits: Limits,
) -> Result<Reservation, StatusCode> {
    let mut active = pool
        .begin()
        .await
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    // One active request per user: other goals or kinds cannot take the shared slots.
    let identity = serde_json::to_string(&("user", uid)).map_err(|_| StatusCode::BAD_REQUEST)?;
    let locked: bool = sqlx::query_scalar(
        "SELECT pg_try_advisory_xact_lock(hashtextextended(current_schema() || ':' || $1, 0))",
    )
    .bind(identity)
    .fetch_one(&mut *active)
    .await
    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    if !locked {
        tracing::warn!("AI request rejected: duplicate active request");
        return Err(StatusCode::CONFLICT);
    }
    let mut transaction = pool
        .begin()
        .await
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    let (month, day): (String, String) = sqlx::query_as(
        "SELECT to_char(t, 'YYYY-MM'), to_char(t, 'YYYY-MM-DD') FROM (SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC' AS t) now",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    sqlx::query("INSERT INTO ai_budget(singleton, month, charged_micro_usd) VALUES(TRUE, $1, 0) ON CONFLICT DO NOTHING")
        .bind(&month).execute(&mut *transaction).await.map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    let (previous, mut charged, mut blocked, previous_day, mut day_charged): (
        String,
        i64,
        bool,
        String,
        i64,
    ) = sqlx::query_as(
        "SELECT month, charged_micro_usd, blocked, day, day_charged_micro_usd FROM ai_budget WHERE singleton FOR UPDATE",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    if previous > month || previous_day > day {
        return Err(StatusCode::SERVICE_UNAVAILABLE);
    }
    if previous != month {
        charged = 0;
        blocked = false;
    }
    if previous_day != day {
        day_charged = 0;
    }
    // The daily cap counts settled spend plus in-flight reservations, so it stops new work only.
    if blocked || day_charged >= limits.day {
        tracing::warn!("AI request rejected: budget limit");
        return Err(StatusCode::TOO_MANY_REQUESTS);
    }
    let total = charged
        .checked_add(amount)
        .filter(|n| amount > 0 && *n <= limits.month)
        .ok_or(StatusCode::TOO_MANY_REQUESTS)
        .inspect_err(|_| tracing::warn!("AI request rejected: budget limit"))?;
    let counted: Option<i32> = sqlx::query_scalar(
        "INSERT INTO ai_daily_usage(day, user_hash, requests) VALUES($1::date, $2, 1) ON CONFLICT(day, user_hash) DO UPDATE SET requests=ai_daily_usage.requests+1 WHERE ai_daily_usage.requests < $3 RETURNING requests",
    )
    .bind(&day)
    .bind(user_hash)
    .bind(limits.user_requests)
    .fetch_optional(&mut *transaction)
    .await
    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    if counted.is_none() {
        // Release the budget row lock before recording the block outside the reservation.
        let _ = transaction.rollback().await;
        let recorded = sqlx::query(
            "INSERT INTO ai_daily_usage(day, user_hash, limited) VALUES($1::date, $2, 1) ON CONFLICT(day, user_hash) DO UPDATE SET limited=ai_daily_usage.limited+1",
        )
        .bind(&day)
        .bind(user_hash)
        .execute(pool)
        .await;
        if recorded.is_err() {
            tracing::warn!("AI request limit count failed");
        }
        tracing::warn!("AI request rejected: user daily limit");
        return Err(StatusCode::TOO_MANY_REQUESTS);
    }
    let metric: i64 =
        sqlx::query_scalar("INSERT INTO ai_request_metrics(kind) VALUES($1) RETURNING id")
            .bind(kind)
            .fetch_one(&mut *transaction)
            .await
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    sqlx::query(
        "UPDATE ai_budget SET month=$1, charged_micro_usd=$2, blocked=FALSE, day=$3, day_charged_micro_usd=$4 WHERE singleton",
    )
    .bind(&month)
    .bind(total)
    .bind(&day)
    .bind(day_charged + amount)
    .execute(&mut *transaction)
    .await
    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    transaction
        .commit()
        .await
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    Ok(Reservation {
        _active: active,
        month,
        day,
        amount,
        metric,
    })
}

impl Reservation {
    pub(super) async fn settle(
        self,
        pool: &PgPool,
        actual: i64,
        overrun: bool,
        limit: i64,
    ) -> Result<(), StatusCode> {
        if actual < 0 || actual > self.amount {
            return Err(StatusCode::SERVICE_UNAVAILABLE);
        }
        if overrun {
            // A violated or unconfirmed ceiling exhausts the budget; never refund it.
            sqlx::query("UPDATE ai_budget SET charged_micro_usd=GREATEST(charged_micro_usd,$1), blocked=TRUE WHERE singleton AND month=$2")
                .bind(limit).bind(&self.month).execute(pool).await.map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        } else {
            sqlx::query("UPDATE ai_budget SET charged_micro_usd=charged_micro_usd-$1, day_charged_micro_usd=CASE WHEN day=$3 THEN day_charged_micro_usd-$1 ELSE day_charged_micro_usd END WHERE singleton AND month=$2 AND NOT blocked")
                .bind(self.amount-actual).bind(&self.month).bind(&self.day).execute(pool).await.map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        }
        // Drop rolls back the advisory-lock transaction. Charged aggregate is already durable.
        Ok(())
    }
}

/// Required also while the feature is OFF. Deployment must run this when the API is stopped.
/// Also expires daily usage after 30 days and request metrics after 90 days.
pub async fn purge_expired(pool: &PgPool) -> Result<(), sqlx::Error> {
    sqlx::query("DELETE FROM ai_budget WHERE month < to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM')")
        .execute(pool).await?;
    sqlx::query(
        "DELETE FROM ai_daily_usage WHERE day < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date - 30",
    )
    .execute(pool)
    .await?;
    sqlx::query(
        "DELETE FROM ai_request_metrics WHERE started_at < CURRENT_TIMESTAMP - INTERVAL '90 days'",
    )
    .execute(pool)
    .await?;
    Ok(())
}

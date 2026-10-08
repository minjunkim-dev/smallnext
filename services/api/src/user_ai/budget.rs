use axum::http::StatusCode;
use sqlx::{PgPool, Postgres, Transaction};

pub(super) struct Reservation {
    // A transaction-scoped advisory lock disappears on connection loss/rollback.
    // No per-request identity is written to PostgreSQL.
    _active: Transaction<'static, Postgres>,
    month: String,
    amount: i64,
}

pub(super) async fn reserve(
    pool: &PgPool,
    uid: &str,
    state: &str,
    kind: &str,
    amount: i64,
    limit: i64,
) -> Result<Reservation, StatusCode> {
    let mut active = pool
        .begin()
        .await
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    // Length-delimited identity prevents uid/state/kind concatenation collisions.
    let identity =
        serde_json::to_string(&(uid, state, kind)).map_err(|_| StatusCode::BAD_REQUEST)?;
    let locked: bool = sqlx::query_scalar(
        "SELECT pg_try_advisory_xact_lock(hashtextextended(current_schema() || ':' || $1, 0))",
    )
    .bind(identity)
    .fetch_one(&mut *active)
    .await
    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    if !locked {
        return Err(StatusCode::CONFLICT);
    }
    let mut transaction = pool
        .begin()
        .await
        .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    let month: String =
        sqlx::query_scalar("SELECT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM')")
            .fetch_one(&mut *transaction)
            .await
            .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    sqlx::query("INSERT INTO ai_budget(singleton, month, charged_micro_usd) VALUES(TRUE, $1, 0) ON CONFLICT DO NOTHING")
        .bind(&month).execute(&mut *transaction).await.map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    let (previous, mut charged, mut blocked): (String, i64, bool) = sqlx::query_as(
        "SELECT month, charged_micro_usd, blocked FROM ai_budget WHERE singleton FOR UPDATE",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    if previous > month {
        return Err(StatusCode::SERVICE_UNAVAILABLE);
    }
    if previous != month {
        charged = 0;
        blocked = false;
    }
    if blocked {
        return Err(StatusCode::TOO_MANY_REQUESTS);
    }
    let total = charged
        .checked_add(amount)
        .filter(|n| amount > 0 && *n <= limit)
        .ok_or(StatusCode::TOO_MANY_REQUESTS)?;
    sqlx::query(
        "UPDATE ai_budget SET month=$1, charged_micro_usd=$2, blocked=FALSE WHERE singleton",
    )
    .bind(&month)
    .bind(total)
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
        amount,
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
            // A violated VERIFIED ceiling exhausts the remaining budget; never refund it.
            sqlx::query("UPDATE ai_budget SET charged_micro_usd=GREATEST(charged_micro_usd,$1), blocked=TRUE WHERE singleton AND month=$2")
                .bind(limit).bind(&self.month).execute(pool).await.map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        } else {
            sqlx::query("UPDATE ai_budget SET charged_micro_usd=charged_micro_usd-$1 WHERE singleton AND month=$2 AND NOT blocked")
                .bind(self.amount-actual).bind(&self.month).execute(pool).await.map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
        }
        // Drop rolls back the advisory-lock transaction. Charged aggregate is already durable.
        Ok(())
    }
}

/// Required also while the feature is OFF. Deployment must run this when the API is stopped.
pub async fn purge_expired(pool: &PgPool) -> Result<(), sqlx::Error> {
    sqlx::query("DELETE FROM ai_budget WHERE month < to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM')")
        .execute(pool).await?;
    Ok(())
}

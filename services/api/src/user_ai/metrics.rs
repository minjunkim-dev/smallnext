//! Anonymous operating metrics for the open beta (#238). No UID, goal, response or token.
use hmac::{Hmac, Mac};
use sqlx::PgPool;

pub(super) fn user_hash(key: &[u8], uid: &str) -> [u8; 32] {
    let mut mac = Hmac::<sha2::Sha256>::new_from_slice(key).expect("HMAC accepts any key length");
    mac.update(uid.as_bytes());
    mac.finalize().into_bytes().into()
}

/// `cost` is None when the reservation was not settled; the budget keeps its ceiling.
pub(super) async fn record(
    pool: &PgPool,
    metric: i64,
    outcome: &str,
    elapsed_ms: u64,
    cost: Option<i64>,
) {
    let result = sqlx::query(
        "UPDATE ai_request_metrics SET outcome=$2, elapsed_ms=$3, cost_micro_usd=$4 WHERE id=$1",
    )
    .bind(metric)
    .bind(outcome)
    .bind(i64::try_from(elapsed_ms).unwrap_or(i64::MAX))
    .bind(cost)
    .execute(pool)
    .await;
    if result.is_err() {
        tracing::warn!("AI request metric update failed");
    }
}

/// Aggregates `[from, to)` in UTC days as JSON. Percentiles are observed values.
pub async fn report(pool: &PgPool, from: &str, to: &str) -> Result<String, sqlx::Error> {
    sqlx::query_scalar(
        "WITH r AS (
            SELECT * FROM ai_request_metrics
            WHERE started_at >= $1::date::timestamp AT TIME ZONE 'UTC'
              AND started_at < $2::date::timestamp AT TIME ZONE 'UTC'
        ), u AS (
            SELECT * FROM ai_daily_usage WHERE day >= $1::date AND day < $2::date
        )
        SELECT jsonb_build_object(
            'from', $1, 'to', $2,
            'requests', (SELECT count(*) FROM r),
            'outcomes', (SELECT COALESCE(jsonb_object_agg(outcome, n), '{}')
                FROM (SELECT outcome, count(*) AS n FROM r GROUP BY outcome) o),
            'latency_ms', (SELECT jsonb_build_object('samples', count(elapsed_ms),
                'p50', percentile_disc(0.5) WITHIN GROUP (ORDER BY elapsed_ms),
                'p95', percentile_disc(0.95) WITHIN GROUP (ORDER BY elapsed_ms),
                'p99', percentile_disc(0.99) WITHIN GROUP (ORDER BY elapsed_ms))
                FROM r WHERE elapsed_ms IS NOT NULL),
            'cost_micro_usd', (SELECT jsonb_build_object('settled_requests', count(cost_micro_usd),
                'total', COALESCE(sum(cost_micro_usd), 0), 'per_request', round(avg(cost_micro_usd)))
                FROM r),
            'users', (SELECT jsonb_build_object('distinct', count(DISTINCT user_hash),
                'limited_requests', COALESCE(sum(limited), 0)) FROM u),
            'daily_users', (SELECT COALESCE(jsonb_object_agg(day, n), '{}')
                FROM (SELECT day::text AS day, count(*) AS n FROM u GROUP BY day) d)
        )::text",
    )
    .bind(from)
    .bind(to)
    .fetch_one(pool)
    .await
}

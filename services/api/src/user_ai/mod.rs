//! User API. The registered flag is OFF until a separate release decision.
mod auth;
pub mod budget;
pub mod metrics;
pub(crate) mod provider;
use crate::suggestion::{AiInput, Disposition, Proposal, validate_input};
use axum::{
    Router,
    body::Bytes,
    extract::{DefaultBodyLimit, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::post,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sqlx::PgPool;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Semaphore;
use utoipa::ToSchema;

#[derive(Clone)]
pub struct Config {
    supabase: auth::Supabase,
    provider: provider::Provider,
    budget_limit: i64,
    daily_limit: i64,
    user_daily_requests: i64,
    usage_key: Vec<u8>,
}

#[derive(Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct SuggestionRequest {
    pub state_key: String,
    pub input: AiInput,
}

#[derive(Serialize, ToSchema)]
pub struct SuggestionResponse {
    pub disposition: String,
    pub proposal: Option<Proposal>,
    pub usage: Vec<provider::Usage>,
    pub elapsed_ms: u64,
}

pub(crate) struct Server {
    config: Config,
    database: PgPool,
    slots: Arc<Semaphore>,
}

impl Config {
    pub fn from_environment() -> Result<Option<Self>, &'static str> {
        let enabled = crate::transport::flag_default("user_server_ai");
        let enabled = match std::env::var("USER_SERVER_AI") {
            Ok(value) => value == "1",
            Err(std::env::VarError::NotPresent) => enabled,
            Err(_) => false,
        };
        if !enabled {
            return Ok(None);
        }
        let url = required("SUPABASE_URL")?;
        let publishable_key = required("SUPABASE_PUBLISHABLE_KEY")?;
        // Public access is explicit; any other value keeps the UID allowlist mandatory.
        let allowed = if std::env::var("AI_PUBLIC_ACCESS").as_deref() == Ok("1") {
            None
        } else {
            Some(
                required("AI_ALLOWED_SUPABASE_UIDS")?
                    .split(',')
                    .map(|v| v.trim().to_owned())
                    .collect(),
            )
        };
        let usage_key = required("AI_USAGE_HASH_KEY")?;
        if usage_key.len() < 32 {
            return Err("AI_USAGE_HASH_KEY must be a random value of at least 32 characters");
        }
        let provider = provider::Provider::from_environment()?;
        // #237 beta ceilings: 30 USD a month, 3 USD a day, 20 requests per user a day.
        let budget_limit = provider::number("AI_BUDGET_MICRO_USD", 30_000_000)? as i64;
        if provider.role_ceiling() * 2 > budget_limit {
            return Err("two full model calls exceed the approved evaluation budget");
        }
        Ok(Some(Self {
            supabase: auth::Supabase::new(url, publishable_key, allowed)?,
            provider,
            budget_limit,
            daily_limit: provider::number("AI_DAILY_BUDGET_MICRO_USD", 3_000_000)? as i64,
            user_daily_requests: provider::number("AI_USER_DAILY_REQUESTS", 20)? as i64,
            usage_key: usage_key.into_bytes(),
        }))
    }
}

#[cfg(test)]
impl Config {
    fn test_config() -> Self {
        Self {
            supabase: auth::Supabase::new(
                "https://test-project.supabase.co".into(),
                "sb_publishable_test".into(),
                Some([tests::identity("allowed"), tests::identity("other")].into()),
            )
            .unwrap(),
            provider: provider::Provider::test_provider(),
            budget_limit: 100_000,
            daily_limit: 100_000,
            user_daily_requests: 1_000,
            usage_key: b"test-usage-key-with-at-least-32-bytes".to_vec(),
        }
    }
    fn with_test_server(mut self, url: String) -> Self {
        self.supabase.endpoints = auth::Endpoints {
            keys: format!("{url}/keys"),
            user: format!("{url}/user"),
        };
        self.provider.endpoint = format!("{url}/messages");
        self
    }
}

pub fn router(config: Option<Config>, database: PgPool) -> Router {
    let Some(config) = config else {
        return Router::new();
    };
    Router::new()
        .route("/v1/suggestions", post(suggest))
        .layer(DefaultBodyLimit::max(32 * 1024))
        .with_state(Arc::new(Server {
            config,
            database,
            slots: Arc::new(Semaphore::new(2)),
        }))
}

#[utoipa::path(post, path="/v1/suggestions", request_body=SuggestionRequest,
    security(("supabaseAccessToken"=[])),
    responses((status=200,description="Checked disposition; only accepted includes a proposal",body=SuggestionResponse),
        (status=400,description="Invalid input"),(status=401,description="Invalid or revoked identity"),
        (status=403,description="UID is not allowed, or browser origin"),(status=404,description="Feature is OFF"),
        (status=409,description="Same user, state and request kind is already active"),
        (status=413,description="Body exceeds 32 KiB"),(status=415,description="JSON required"),
        (status=429,description="Monthly or daily budget, or the user's daily request limit, is reached"),
        (status=503,description="Authentication, database or request capacity unavailable"),
        (status=504,description="Authentication deadline exceeded"))) ]
pub(crate) async fn suggest(
    State(server): State<Arc<Server>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let started = Instant::now();
    let timing_id = crate::timing::run_id(&headers);
    if let Err(status) = crate::transport::json_request(&headers) {
        return status.into_response();
    }
    let uid = match tokio::time::timeout(
        Duration::from_secs(20),
        server.config.supabase.authorize(&headers, &server.database),
    )
    .await
    {
        Ok(Ok(uid)) => uid,
        Ok(Err(status)) => {
            // Fixed text and status only: operators count rejected identities from host logs.
            tracing::warn!(
                status = status.as_u16(),
                "AI request rejected: authentication"
            );
            return status.into_response();
        }
        Err(_) => {
            tracing::warn!(status = 504, "AI request rejected: authentication");
            return StatusCode::GATEWAY_TIMEOUT.into_response();
        }
    };
    let Ok(request) = serde_json::from_slice::<SuggestionRequest>(&body) else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    if !crate::transport::valid_state_key(&request.state_key) {
        return StatusCode::BAD_REQUEST.into_response();
    }
    if validate_input(&request.input).is_err() {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let Ok(slot) = server.slots.clone().try_acquire_owned() else {
        tracing::warn!("AI request rejected: capacity");
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    let reservation = match budget::reserve(
        &server.database,
        &uid,
        &metrics::user_hash(&server.config.usage_key, &uid),
        request
            .input
            .request_kind
            .as_deref()
            .unwrap_or("first_action"),
        server.config.provider.role_ceiling() * 2,
        budget::Limits {
            month: server.config.budget_limit,
            day: server.config.daily_limit,
            user_requests: server.config.user_daily_requests,
        },
    )
    .await
    {
        Ok(value) => value,
        Err(status) => return status.into_response(),
    };
    // Hyper owns the future. Drop aborts auth/provider I/O and rolls back the active lock.
    // The committed reservation remains charged if cancellation prevents settlement.
    let future = async move {
        let _slot = slot;
        let metric = reservation.metric;
        let (disposition, proposal, usage, cost) = match tokio::time::timeout(
            Duration::from_secs(120),
            server.config.provider.evaluate(&request.input),
        )
        .await
        {
            Err(_) => (Disposition::TimedOut, None, Vec::new(), None),
            Ok(evaluation) => {
                if reservation
                    .settle(
                        &server.database,
                        evaluation.charged,
                        evaluation.overrun,
                        server.config.budget_limit,
                    )
                    .await
                    .is_err()
                {
                    (Disposition::Failed, None, evaluation.usage, None)
                } else {
                    let cost = Some(evaluation.charged);
                    match evaluation.result {
                        Ok(proposal) => (
                            Disposition::Accepted,
                            Some(proposal),
                            evaluation.usage,
                            cost,
                        ),
                        Err(reason) => (reason, None, evaluation.usage, cost),
                    }
                }
            }
        };
        let disposition: String = serde_json::to_value(disposition)
            .unwrap()
            .as_str()
            .unwrap()
            .into();
        let elapsed_ms = started.elapsed().as_millis().min(u64::MAX as u128) as u64;
        metrics::record(&server.database, metric, &disposition, elapsed_ms, cost).await;
        let response = SuggestionResponse {
            disposition,
            proposal,
            usage,
            elapsed_ms,
        };
        Bytes::from(serde_json::to_vec(&response).expect("finite checked response"))
    };
    crate::transport::deferred_response(crate::timing::response(timing_id, started, future))
}

fn required(name: &str) -> Result<String, &'static str> {
    std::env::var(name)
        .ok()
        .filter(|v| !v.trim().is_empty() && !v.contains(['\r', '\n']))
        .ok_or("missing or invalid user AI configuration; see docs/SERVER_AI.md")
}

fn client() -> Result<reqwest::Client, &'static str> {
    reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .timeout(Duration::from_secs(30))
        .connect_timeout(Duration::from_secs(5))
        .build()
        .map_err(|_| "cannot initialize HTTPS client")
}

async fn read_json(mut response: reqwest::Response, limit: usize) -> Result<Value, ()> {
    if !response.status().is_success()
        || response.content_length().is_some_and(|n| n > limit as u64)
    {
        return Err(());
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| ())? {
        if bytes.len().saturating_add(chunk.len()) > limit {
            return Err(());
        }
        bytes.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&bytes).map_err(|_| ())
}

#[cfg(test)]
mod test_key;
#[cfg(test)]
mod tests;

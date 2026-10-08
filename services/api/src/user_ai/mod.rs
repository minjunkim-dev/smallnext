//! User API. The registered flag is OFF until a separate release decision.
mod auth;
pub mod budget;
pub(crate) mod provider;
use crate::development_ai::{AiInput, Disposition, Proposal, validate_input};
use axum::{
    Router,
    body::Bytes,
    extract::{DefaultBodyLimit, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
    routing::post,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
#[cfg(test)]
use serde_json::json;
use sqlx::PgPool;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Semaphore;
use utoipa::ToSchema;

#[derive(Clone)]
pub struct Config {
    firebase: auth::Firebase,
    provider: provider::Provider,
    budget_limit: i64,
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
        let registry: Value =
            serde_json::from_str(include_str!("../../../../config/feature-flags.json"))
                .unwrap_or(Value::Null);
        let enabled = registry["version"] == 1
            && registry["flags"].as_array().is_some_and(|flags| {
                let matches: Vec<_> = flags
                    .iter()
                    .filter(|f| f["key"] == "user_server_ai")
                    .collect();
                matches.len() == 1 && matches[0]["default"] == true
            });
        if !enabled && std::env::var("USER_SERVER_AI").as_deref() != Ok("1") {
            return Ok(None);
        }
        let project = required("FIREBASE_PROJECT_ID")?;
        let allowed = required("AI_ALLOWED_FIREBASE_UIDS")?
            .split(',')
            .map(|v| v.trim().to_owned())
            .collect();
        let path = required("FIREBASE_SERVICE_ACCOUNT_FILE")?;
        let bytes = std::fs::read(path).map_err(|_| "cannot read Firebase service account file")?;
        if bytes.len() > 64 * 1024 {
            return Err("Firebase service account file is too large");
        }
        let provider = provider::Provider::from_environment()?;
        let budget_limit = provider::number("AI_BUDGET_MICRO_USD", 3_000_000)? as i64;
        if provider.role_ceiling() * 2 > budget_limit {
            return Err("two full model calls exceed the approved evaluation budget");
        }
        Ok(Some(Self {
            firebase: auth::Firebase::new(project, allowed, &bytes)?,
            provider,
            budget_limit,
        }))
    }
}

#[cfg(test)]
impl Config {
    fn test_config() -> Self {
        Self { firebase: auth::Firebase::new("test-project".into(), ["allowed".into(), "other".into()].into(),
            &serde_json::to_vec(&json!({"type":"service_account","project_id":"test-project",
            "client_email":"test@test-project.iam.gserviceaccount.com","private_key":test_key::PRIVATE})).unwrap()).unwrap(),
            provider: provider::Provider::test_provider(), budget_limit:100_000 }
    }
    fn with_test_server(mut self, url: String) -> Self {
        self.firebase.endpoints = auth::Endpoints {
            keys: format!("{url}/keys"),
            oauth: format!("{url}/oauth"),
            lookup: format!("{url}/accounts"),
        };
        self.provider.endpoint = format!("{url}/responses");
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
    security(("firebaseIdToken"=[])),
    responses((status=200,description="Checked disposition; only accepted includes a proposal",body=SuggestionResponse),
        (status=400,description="Invalid input"),(status=401,description="Invalid or revoked identity"),
        (status=403,description="UID is not allowed, or browser origin"),(status=404,description="Feature is OFF"),
        (status=409,description="Same user, state and request kind is already active"),
        (status=413,description="Body exceeds 32 KiB"),(status=415,description="JSON required"),
        (status=429,description="Two-call reservation exceeds budget"),
        (status=503,description="Authentication, database or request capacity unavailable"),
        (status=504,description="Authentication deadline exceeded"))) ]
pub(crate) async fn suggest(
    State(server): State<Arc<Server>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let started = Instant::now();
    if headers.contains_key(header::ORIGIN) {
        return StatusCode::FORBIDDEN.into_response();
    }
    if headers
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .is_none_or(|v| v.split(';').next().unwrap_or("").trim() != "application/json")
    {
        return StatusCode::UNSUPPORTED_MEDIA_TYPE.into_response();
    }
    let uid = match tokio::time::timeout(
        Duration::from_secs(20),
        server.config.firebase.authorize(&headers),
    )
    .await
    {
        Ok(Ok(uid)) => uid,
        Ok(Err(status)) => return status.into_response(),
        Err(_) => return StatusCode::GATEWAY_TIMEOUT.into_response(),
    };
    let Ok(request) = serde_json::from_slice::<SuggestionRequest>(&body) else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    if request.state_key.trim().is_empty()
        || request.state_key.len() > 128
        || request.state_key.chars().any(char::is_control)
    {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let original = match validate_input(&request.input) {
        Ok(v) => v,
        Err(_) => return StatusCode::BAD_REQUEST.into_response(),
    };
    let Ok(slot) = server.slots.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    let reservation = match budget::reserve(
        &server.database,
        &uid,
        &request.state_key,
        request
            .input
            .request_kind
            .as_deref()
            .unwrap_or("first_action"),
        server.config.provider.role_ceiling() * 2,
        server.config.budget_limit,
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
        let (disposition, proposal, usage) = match tokio::time::timeout(
            Duration::from_secs(120),
            server.config.provider.evaluate(&request.input, original),
        )
        .await
        {
            Err(_) => (Disposition::TimedOut, None, Vec::new()),
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
                    (Disposition::Failed, None, evaluation.usage)
                } else {
                    match evaluation.result {
                        Ok(proposal) => (Disposition::Accepted, Some(proposal), evaluation.usage),
                        Err(reason) => (reason, None, evaluation.usage),
                    }
                }
            }
        };
        let response = SuggestionResponse {
            disposition: serde_json::to_value(disposition)
                .unwrap()
                .as_str()
                .unwrap()
                .into(),
            proposal,
            usage,
            elapsed_ms: started.elapsed().as_millis().min(u64::MAX as u128) as u64,
        };
        Bytes::from(serde_json::to_vec(&response).expect("finite checked response"))
    };
    crate::development_ai::http::deferred_response(future)
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

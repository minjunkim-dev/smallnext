//! Private development transport. Deliberately excluded from the product OpenAPI.
use super::{ActionState, AiInput, INPUT_LIMIT, SubscriptionAi};
use crate::transport::{deferred_response, json_request, valid_state_key};
use axum::{
    Json, Router,
    body::Bytes,
    extract::{DefaultBodyLimit, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
    routing::post,
};
use serde::Deserialize;
use serde_json::json;
use std::{
    collections::HashSet,
    env,
    net::SocketAddr,
    sync::{Arc, Mutex},
};

#[derive(Clone)]
struct Server {
    ai: Arc<SubscriptionAi>,
    token: Option<String>,
    active: Arc<Mutex<HashSet<String>>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    state_key: String,
    input: AiInput,
}

/// Only an explicit local environment override enables the registered development flag.
pub fn from_environment(address: SocketAddr) -> Result<Router, &'static str> {
    let ai = if env::var("DEVELOPMENT_SUBSCRIPTION_AI").as_deref() == Ok("1") {
        SubscriptionAi::for_local_development()
    } else {
        SubscriptionAi::default()
    };
    let token = env::var("DEVELOPMENT_AI_TOKEN")
        .ok()
        .filter(|s| !s.trim().is_empty());
    if ai.enabled && !address.ip().is_loopback() && token.is_none() {
        return Err("LAN development AI requires DEVELOPMENT_AI_TOKEN in local .env");
    }
    if token.as_ref().is_some_and(|s| s.contains(['\r', '\n'])) {
        return Err("invalid DEVELOPMENT_AI_TOKEN");
    }
    Ok(router(ai, token))
}

pub fn router(ai: SubscriptionAi, token: Option<String>) -> Router {
    if !ai.enabled {
        return Router::new();
    }
    Router::new()
        .route("/development/suggestions", post(suggest))
        .layer(DefaultBodyLimit::max(INPUT_LIMIT))
        .with_state(Server {
            ai: Arc::new(ai),
            token,
            active: Arc::default(),
        })
}

async fn suggest(State(server): State<Server>, headers: HeaderMap, body: Bytes) -> Response {
    let started = std::time::Instant::now();
    let timing_id = crate::timing::run_id(&headers);
    if let Err(status) = json_request(&headers) {
        return status.into_response();
    }
    if let Some(token) = &server.token
        && headers
            .get(header::AUTHORIZATION)
            .and_then(|s| s.to_str().ok())
            != Some(format!("Bearer {token}").as_str())
    {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(request) = serde_json::from_slice::<Request>(&body) else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    if !valid_state_key(&request.state_key) {
        return StatusCode::BAD_REQUEST.into_response();
    }
    if !server
        .active
        .lock()
        .expect("active request lock")
        .insert(request.state_key.clone())
    {
        return (StatusCode::CONFLICT, Json(json!({"disposition":"busy"}))).into_response();
    }
    let lease = Lease {
        key: request.state_key,
        active: server.active,
    };
    // Hyper owns this future through its response body. Disconnect drops it, the lease,
    // and the running CLI (kill_on_drop). No detached generation task survives a client.
    let future = async move {
        let _lease = lease;
        let mut state = ActionState::new(None);
        let ticket = state.begin().expect("new action state");
        let outcome = server.ai.evaluate(&request.input, ticket).await;
        let disposition = outcome.disposition;
        let accepted = state.finish(outcome);
        Bytes::from(
            json!({"disposition": disposition,
            "proposal": if accepted { state.current() } else { &None }})
            .to_string(),
        )
    };
    deferred_response(crate::timing::response(timing_id, started, future))
}

struct Lease {
    key: String,
    active: Arc<Mutex<HashSet<String>>>,
}
impl Drop for Lease {
    fn drop(&mut self) {
        self.active
            .lock()
            .expect("active request lock")
            .remove(&self.key);
    }
}

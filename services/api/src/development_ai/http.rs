//! Private development transport. Deliberately excluded from the product OpenAPI.
use super::{ActionState, AiInput, INPUT_LIMIT, SubscriptionAi};
use axum::{
    Json, Router,
    body::{Body, Bytes, HttpBody},
    extract::{DefaultBodyLimit, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
    routing::post,
};
use http_body::Frame;
use serde::Deserialize;
use serde_json::json;
use std::{
    collections::HashSet,
    convert::Infallible,
    env,
    future::Future,
    net::SocketAddr,
    pin::Pin,
    sync::{Arc, Mutex},
    task::{Context, Poll},
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
    // A web page must not spend the developer's CLI allowance through a simple localhost POST.
    if headers.contains_key(header::ORIGIN) {
        return StatusCode::FORBIDDEN.into_response();
    }
    if headers
        .get(header::CONTENT_TYPE)
        .and_then(|s| s.to_str().ok())
        .is_none_or(|s| s.split(';').next().unwrap_or("").trim() != "application/json")
    {
        return StatusCode::UNSUPPORTED_MEDIA_TYPE.into_response();
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
    if request.state_key.is_empty() || request.state_key.len() > 128 {
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
    let future = Box::pin(async move {
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
    });
    (
        [
            (header::CONTENT_TYPE, "application/json"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        Body::new(SuggestionBody(Some(future))),
    )
        .into_response()
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

struct SuggestionBody(Option<Pin<Box<dyn Future<Output = Bytes> + Send>>>);
impl HttpBody for SuggestionBody {
    type Data = Bytes;
    type Error = Infallible;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Infallible>>> {
        let Some(future) = self.0.as_mut() else {
            return Poll::Ready(None);
        };
        match future.as_mut().poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(bytes) => {
                self.0 = None;
                Poll::Ready(Some(Ok(Frame::data(bytes))))
            }
        }
    }
}

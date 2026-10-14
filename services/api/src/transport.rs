//! Request rules and the deferred JSON body shared by the suggestion routes.
use axum::{
    body::{Body, Bytes, HttpBody},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
};
use http_body::Frame;
use serde_json::Value;
use std::{
    convert::Infallible,
    future::Future,
    pin::Pin,
    task::{Context, Poll},
};

/// Registered default of one flag. A malformed registry or a duplicate key is OFF.
pub(crate) fn flag_default(key: &str) -> bool {
    let registry: Value = serde_json::from_str(include_str!("../../../config/feature-flags.json"))
        .unwrap_or(Value::Null);
    registry["version"] == 1
        && registry["flags"].as_array().is_some_and(|flags| {
            let matching: Vec<_> = flags.iter().filter(|f| f["key"] == key).collect();
            matching.len() == 1 && matching[0]["default"] == true
        })
}

/// A web page must not spend model allowance through a simple cross-site POST.
pub(crate) fn json_request(headers: &HeaderMap) -> Result<(), StatusCode> {
    if headers.contains_key(header::ORIGIN) {
        return Err(StatusCode::FORBIDDEN);
    }
    if headers
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .is_none_or(|v| v.split(';').next().unwrap_or("").trim() != "application/json")
    {
        return Err(StatusCode::UNSUPPORTED_MEDIA_TYPE);
    }
    Ok(())
}

pub(crate) fn valid_state_key(key: &str) -> bool {
    !key.trim().is_empty() && key.len() <= 128 && !key.chars().any(char::is_control)
}

/// Hyper owns the future through the body, so a client disconnect drops the running work.
pub(crate) fn deferred_response(future: impl Future<Output = Bytes> + Send + 'static) -> Response {
    (
        [
            (header::CONTENT_TYPE, "application/json"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        Body::new(DeferredBody(Some(Box::pin(future)))),
    )
        .into_response()
}

struct DeferredBody(Option<Pin<Box<dyn Future<Output = Bytes> + Send>>>);
impl HttpBody for DeferredBody {
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

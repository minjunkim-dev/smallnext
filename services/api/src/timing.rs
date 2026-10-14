//! Opt-in Debug diagnostics. No raw input, identity, model output or cross-process timestamps.
use axum::{body::Bytes, http::HeaderMap};
use serde::Serialize;
use std::{future::Future, sync::Mutex, time::Instant};

#[derive(Default, Serialize)]
struct Timing {
    run_id: String,
    generate_ms: Option<f64>,
    check_ms: Option<f64>,
    total_ms: f64,
}

tokio::task_local! { static CURRENT: Mutex<Timing>; }

pub(crate) fn run_id(headers: &HeaderMap) -> Option<String> {
    if !cfg!(debug_assertions) {
        return None;
    }
    let id = headers.get("x-smallnext-timing")?.to_str().ok()?;
    (id.len() == 36
        && id.bytes().enumerate().all(|(i, c)| {
            if [8, 13, 18, 23].contains(&i) {
                c == b'-'
            } else {
                c.is_ascii_hexdigit()
            }
        }))
    .then(|| id.to_owned())
}

pub(crate) async fn measure<T>(
    role: crate::suggestion::Role,
    future: impl Future<Output = T>,
) -> T {
    let started = CURRENT.try_with(|_| Instant::now()).ok();
    let result = future.await;
    if let Some(started) = started {
        let _ = CURRENT.try_with(|timing| {
            let mut timing = timing.lock().expect("timing lock");
            let elapsed = Some(started.elapsed().as_secs_f64() * 1000.0);
            match role {
                crate::suggestion::Role::Generate => timing.generate_ms = elapsed,
                crate::suggestion::Role::Check => timing.check_ms = elapsed,
            }
        });
    }
    result
}

pub(crate) async fn response(
    id: Option<String>,
    started: Instant,
    future: impl Future<Output = Bytes>,
) -> Bytes {
    let Some(run_id) = id else {
        return future.await;
    };
    CURRENT
        .scope(
            Mutex::new(Timing {
                run_id,
                ..Timing::default()
            }),
            async {
                let bytes = future.await;
                let mut value: serde_json::Value =
                    serde_json::from_slice(&bytes).expect("JSON response");
                CURRENT.with(|timing| {
                    let mut timing = timing.lock().expect("timing lock");
                    timing.total_ms = started.elapsed().as_secs_f64() * 1000.0;
                    value["_timing"] = serde_json::to_value(&*timing).expect("finite timing");
                });
                Bytes::from(value.to_string())
            },
        )
        .await
}

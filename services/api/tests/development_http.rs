use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use smallnext_api::development_ai::{SubscriptionAi, http};
use tower::ServiceExt;

#[tokio::test]
async fn disabled_flag_has_no_development_route() {
    let response = http::router(SubscriptionAi::default(), None)
        .oneshot(
            Request::post("/development/suggestions")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn configured_token_rejects_missing_or_wrong_authorization() {
    let app = http::router(
        SubscriptionAi::for_local_development(),
        Some("local-test-token".into()),
    );
    for token in ["", "Bearer wrong"] {
        let response = app
            .clone()
            .oneshot(
                Request::post("/development/suggestions")
                    .header("Authorization", token)
                    .header("Content-Type", "application/json")
                    .body(Body::from("{}"))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }
}

#[test]
fn lan_binding_without_local_token_fails_before_connecting_database() {
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_smallnext-api"))
        .env("API_BIND_ADDRESS", "0.0.0.0:0")
        .env("DEVELOPMENT_SUBSCRIPTION_AI", "1")
        .env_remove("DEVELOPMENT_AI_TOKEN")
        .env(
            "DATABASE_URL",
            "postgres://unused:unused@127.0.0.1:1/unused",
        )
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(
        String::from_utf8_lossy(&output.stderr)
            .contains("LAN development AI requires DEVELOPMENT_AI_TOKEN")
    );
}

#[tokio::test]
async fn browser_origin_and_oversized_input_never_start_cli() {
    let app = http::router(SubscriptionAi::for_local_development(), None);
    let response = app
        .clone()
        .oneshot(
            Request::post("/development/suggestions")
                .header("Content-Type", "application/json")
                .header("Origin", "https://untrusted.invalid")
                .body(Body::from("{}"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
    let response = app
        .oneshot(
            Request::post("/development/suggestions")
                .header("Content-Type", "application/json")
                .body(Body::from("x".repeat(32 * 1024 + 1)))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use sqlx::postgres::PgPoolOptions;
use std::time::Duration;
use tower::ServiceExt;

#[tokio::test]
async fn health_does_not_require_a_database_connection() {
    let database = PgPoolOptions::new()
        .connect_lazy("postgres://local:local@127.0.0.1:1/unused")
        .unwrap();
    let response = smallnext_api::router(database)
        .oneshot(
            Request::builder()
                .uri("/health")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let expected: serde_json::Value =
        serde_json::from_str(include_str!("../../../contracts/fixtures/health.json")).unwrap();
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&bytes).unwrap(),
        expected
    );
}

#[tokio::test]
async fn readiness_reports_an_unavailable_database_without_exposing_details() {
    let database = PgPoolOptions::new()
        .acquire_timeout(Duration::from_millis(100))
        .connect_lazy("postgres://local:local@127.0.0.1:1/unused")
        .unwrap();
    let response = smallnext_api::router(database)
        .oneshot(
            Request::builder()
                .uri("/ready")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&bytes).unwrap(),
        serde_json::json!({"status": "unavailable"})
    );
}

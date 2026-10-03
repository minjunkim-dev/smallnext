use sqlx::postgres::PgPoolOptions;

// Run explicitly against an isolated local/CI database. No implicit production connection.
#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL"]
async fn bootstrap_migration_is_repeatable_and_readiness_succeeds() {
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use tower::ServiceExt;

    let url = std::env::var("TEST_DATABASE_URL").expect("set TEST_DATABASE_URL");
    let database = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .unwrap();
    smallnext_api::migrate(&database).await.unwrap();
    smallnext_api::migrate(&database).await.unwrap();
    let value: String =
        sqlx::query_scalar("SELECT value FROM app_metadata WHERE key = 'schema_version'")
            .fetch_one(&database)
            .await
            .unwrap();
    assert_eq!(value, "1");
    let response = smallnext_api::router(database)
        .oneshot(
            Request::builder()
                .uri("/ready")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
}

use axum::{Json, Router, extract::State, http::StatusCode, routing::get};
use serde::{Deserialize, Serialize};
use sqlx::PgPool;
use utoipa::{OpenApi, ToSchema};

#[derive(Clone)]
pub struct AppState {
    pub database: PgPool,
}

#[derive(Debug, Serialize, Deserialize, ToSchema, PartialEq)]
pub struct HealthResponse {
    pub status: String,
}

#[utoipa::path(
    get, path = "/health",
    responses((status = 200, description = "API process is running", body = HealthResponse))
)]
async fn health() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".into(),
    })
}

#[utoipa::path(
    get, path = "/ready",
    responses(
        (status = 200, description = "Database is reachable", body = HealthResponse),
        (status = 503, description = "Database is unavailable", body = HealthResponse)
    )
)]
async fn ready(State(state): State<AppState>) -> (StatusCode, Json<HealthResponse>) {
    match sqlx::query("SELECT 1").execute(&state.database).await {
        Ok(_) => (
            StatusCode::OK,
            Json(HealthResponse {
                status: "ok".into(),
            }),
        ),
        Err(error) => {
            tracing::warn!(%error, "database readiness check failed");
            (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(HealthResponse {
                    status: "unavailable".into(),
                }),
            )
        }
    }
}

#[derive(OpenApi)]
#[openapi(
    info(title = "Smallnext API", version = "0.1.0"),
    paths(health, ready),
    components(schemas(HealthResponse))
)]
pub struct ApiDoc;

pub fn api_document() -> utoipa::openapi::OpenApi {
    let mut document = ApiDoc::openapi();
    // The project has not selected a public license yet.
    document.info.license = None;
    document
}

pub fn router(database: PgPool) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/ready", get(ready))
        .route("/openapi.json", get(|| async { Json(api_document()) }))
        .with_state(AppState { database })
}

pub async fn migrate(database: &PgPool) -> Result<(), sqlx::migrate::MigrateError> {
    sqlx::migrate!().run(database).await
}

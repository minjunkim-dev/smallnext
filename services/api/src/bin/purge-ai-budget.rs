//! Deployment scheduler entry point; no auth or provider network calls.
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(&std::env::var("DATABASE_URL")?)
        .await?;
    smallnext_api::user_ai::budget::purge_expired(&pool).await?;
    Ok(())
}

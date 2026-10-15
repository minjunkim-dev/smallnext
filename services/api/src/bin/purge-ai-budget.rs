//! Deployment scheduler entry point; no auth or provider network calls.
#[tokio::main]
async fn main() -> std::process::ExitCode {
    match purge().await {
        Ok(()) => {
            println!("AI budget purge completed");
            std::process::ExitCode::SUCCESS
        }
        Err(_) => {
            // Database errors can contain connection details; keep host logs value-free.
            eprintln!("AI budget purge failed");
            std::process::ExitCode::FAILURE
        }
    }
}

async fn purge() -> Result<(), Box<dyn std::error::Error>> {
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(&std::env::var("DATABASE_URL")?)
        .await?;
    smallnext_api::user_ai::budget::purge_expired(&pool).await?;
    Ok(())
}

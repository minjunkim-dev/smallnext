//! Explicit schema migration entry point. Only this process receives the migration DSN.
#[tokio::main]
async fn main() -> std::process::ExitCode {
    match migrate().await {
        Ok(()) => {
            println!("API migration completed");
            std::process::ExitCode::SUCCESS
        }
        Err(_) => {
            // Database errors can contain credentials. Keep diagnostics value-free.
            eprintln!("API migration failed");
            std::process::ExitCode::FAILURE
        }
    }
}

async fn migrate() -> Result<(), Box<dyn std::error::Error>> {
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(&std::env::var("DATABASE_URL")?)
        .await?;
    smallnext_api::migrate(&pool).await?;
    Ok(())
}

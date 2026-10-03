use sqlx::postgres::PgPoolOptions;
use std::{env, net::SocketAddr, time::Duration};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| "smallnext_api=info".into()),
        )
        .init();

    let database_url = env::var("DATABASE_URL")?;
    let address: SocketAddr = env::var("API_BIND_ADDRESS")
        .unwrap_or_else(|_| "127.0.0.1:8080".into())
        .parse()?;
    let database = PgPoolOptions::new()
        .max_connections(5)
        .acquire_timeout(Duration::from_secs(5))
        .connect(&database_url)
        .await?;
    smallnext_api::migrate(&database).await?;
    let listener = tokio::net::TcpListener::bind(address).await?;
    tracing::info!(%address, "API listening");
    axum::serve(listener, smallnext_api::router(database))
        .with_graceful_shutdown(shutdown())
        .await?;
    Ok(())
}

async fn shutdown() {
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("could not install SIGTERM handler");
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {},
            _ = terminate.recv() => {},
        }
    }
    #[cfg(not(unix))]
    let _ = tokio::signal::ctrl_c().await;
}

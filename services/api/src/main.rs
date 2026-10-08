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
    let development = smallnext_api::development_ai::http::from_environment(address)?;
    let user_ai = smallnext_api::user_ai::Config::from_environment()?;
    let database = PgPoolOptions::new()
        .max_connections(5)
        .acquire_timeout(Duration::from_secs(5))
        .connect(&database_url)
        .await?;
    smallnext_api::migrate(&database).await?;
    smallnext_api::user_ai::budget::purge_expired(&database).await?;
    let maintenance_database = database.clone();
    let maintenance = tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(60));
        loop {
            interval.tick().await;
            if smallnext_api::user_ai::budget::purge_expired(&maintenance_database)
                .await
                .is_err()
            {
                tracing::warn!("expired AI budget purge failed");
            }
        }
    });
    let listener = tokio::net::TcpListener::bind(address).await?;
    tracing::info!(%address, "API listening");
    let user_ai = smallnext_api::user_ai::router(user_ai, database.clone());
    axum::serve(
        listener,
        smallnext_api::router(database)
            .merge(development)
            .merge(user_ai),
    )
    .with_graceful_shutdown(shutdown())
    .await?;
    maintenance.abort();
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

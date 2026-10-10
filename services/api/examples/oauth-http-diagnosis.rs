#[tokio::main]
async fn main() {
    let ai = smallnext_api::development_ai::SubscriptionAi::for_local_development();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:18996")
        .await
        .unwrap();
    axum::serve(
        listener,
        smallnext_api::development_ai::http::router(ai, None),
    )
    .await
    .unwrap();
}

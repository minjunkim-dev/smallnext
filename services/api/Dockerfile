FROM rust:1.98-bookworm AS builder
WORKDIR /workspace
COPY services/api/Cargo.toml services/api/Cargo.lock ./
# Build dependencies in their own layer so source edits reuse the cached layer.
RUN mkdir src && echo 'fn main() {}' > src/main.rs && touch src/lib.rs \
    && cargo build --release --locked --bin smallnext-api \
    && rm -rf src target/release/.fingerprint/smallnext-api-*
COPY services/api/src ./src
COPY services/api/migrations ./migrations
RUN cargo build --release --locked --bin smallnext-api

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home smallnext
COPY --from=builder /workspace/target/release/smallnext-api /usr/local/bin/smallnext-api
USER smallnext
ENV API_BIND_ADDRESS=0.0.0.0:8080
EXPOSE 8080
CMD ["smallnext-api"]

FROM rust:1.99.1-bookworm@sha256:e12566d5abc17a0da741628782cdb504b68b8961f5bfcf677936bf3e8b32de29 AS builder
WORKDIR /workspace/services/api
COPY services/api/Cargo.toml services/api/Cargo.lock ./
# Build dependencies in their own layer so source edits reuse the cached layer.
RUN mkdir src && echo 'fn main() {}' > src/main.rs && touch src/lib.rs \
    && cargo build --release --locked --bin smallnext-api \
    && rm -rf src target/release/.fingerprint/smallnext-api-*
COPY services/api/src ./src
COPY services/api/migrations ./migrations
COPY services/api/build.rs ./
COPY config/feature-flags.json /workspace/config/feature-flags.json
RUN cargo build --release --locked --bin smallnext-api --bin purge-ai-budget --bin migrate-api

FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home smallnext
COPY --from=builder /workspace/services/api/target/release/smallnext-api /usr/local/bin/smallnext-api
COPY --from=builder /workspace/services/api/target/release/purge-ai-budget /usr/local/bin/purge-ai-budget
COPY --from=builder /workspace/services/api/target/release/migrate-api /usr/local/bin/migrate-api
USER smallnext
ENV API_BIND_ADDRESS=0.0.0.0:8080
EXPOSE 8080
CMD ["smallnext-api"]

use axum::{
    Json, Router,
    extract::State,
    routing::{get, post},
};
use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use serde_json::json;
use sqlx::postgres::PgPoolOptions;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU64, Ordering},
};
use tower::ServiceExt;

#[derive(Default)]
struct Remote {
    calls: Mutex<Vec<serde_json::Value>>,
    disabled: std::sync::atomic::AtomicBool,
    revoked_after: AtomicU64,
    mode: Mutex<String>,
    delay_ms: AtomicU64,
}

async fn external_provider(
    State(remote): State<Arc<Remote>>,
    headers: axum::http::HeaderMap,
    Json(body): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    assert_eq!(headers["x-api-key"], "test-provider");
    assert_eq!(headers["anthropic-version"], "2023-06-01");
    assert!(!headers.contains_key("authorization"));
    remote.calls.lock().unwrap().push(body.clone());
    let delay = remote.delay_ms.load(Ordering::SeqCst);
    if delay > 0 {
        tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
    }
    let mode = remote.mode.lock().unwrap().clone();
    let original: serde_json::Value =
        serde_json::from_str(body["messages"][0]["content"].as_str().unwrap()).unwrap();
    let generating = body["output_config"]["format"]["schema"]["properties"]
        .get("action")
        .is_some();
    let value = if generating {
        json!({"status": match mode.as_str() { "minimum" | "no_action" | "goal_summary" | "need_info" => mode.as_str(), _ => "action" },"action":"펜 하나 옮기기","completion_condition":"펜이 펜꽂이에 있다",
            "estimated_minutes":1,"reason":"한 물건만 옮긴다","remaining_work":original["remaining_work"],
            "preserved_completed_ids":original["completed_ids"],"goal_completed":mode=="invalid","current_action_completed":false})
    } else {
        json!({"verdict":if mode=="reject" || mode=="uncertain" { mode.as_str() } else { "accept" },"criteria":[1,2,3,4,5],"evidence":"원본과 일치","reason":"판정"})
    };
    let mut response = json!({"type":"message","role":"assistant","model":"claude-haiku-5-5","stop_reason":"end_turn",
        "content":[{"type":"thinking","thinking":"합성","signature":"test"},{"type":"text","text":value.to_string()}],
        "usage":{"input_tokens":8,"output_tokens":7,"cache_read_input_tokens":3,"cache_creation_input_tokens":0,
            "output_tokens_details":{"thinking_tokens":2}}});
    if mode == "missing_usage" {
        response["usage"] = serde_json::Value::Null;
    }
    if mode == "overrun" {
        response["usage"]["output_tokens"] = json!(1001);
    }
    if (mode == "wrong_generate_model" && generating)
        || (mode == "wrong_check_model" && !generating)
    {
        response["model"] = json!("unconfirmed-model");
    }
    match mode.as_str() {
        "truncated" => response["stop_reason"] = json!("max_tokens"),
        "refusal" => response["stop_details"] = json!({"type":"refusal"}),
        "tool" => {
            response["content"][0] =
                json!({"type":"tool_use","id":"tool-test","name":"unexpected","input":{}})
        }
        "cache_overrun" => {
            response["usage"]["cache_creation_input_tokens"] = json!(20_000);
            response["usage"]["cache_read_input_tokens"] = json!(0);
        }
        _ => {}
    }
    Json(response)
}

struct Fixture {
    app: Router,
    config: super::Config,
    database: sqlx::PgPool,
    remote: Arc<Remote>,
    server: tokio::task::JoinHandle<()>,
    admin: sqlx::PgPool,
    schema: String,
}
impl Fixture {
    async fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let schema = format!(
            "test_user_ai_{}_{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        );
        let url = std::env::var("TEST_DATABASE_URL")
            .expect("explicit isolated TEST_DATABASE_URL required");
        let admin = PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
            .unwrap();
        sqlx::query(&format!("CREATE SCHEMA {schema}"))
            .execute(&admin)
            .await
            .unwrap();
        let options: sqlx::postgres::PgConnectOptions = url.parse().unwrap();
        let database = PgPoolOptions::new()
            .max_connections(8)
            .acquire_timeout(std::time::Duration::from_secs(2))
            .connect_with(options.options([("search_path", schema.as_str())]))
            .await
            .unwrap();
        crate::migrate(&database).await.unwrap();
        let remote = Arc::new(Remote::default());
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let upstream = Router::new().route("/keys", get(|| async {
            ([("Cache-Control","max-age=300")], Json(json!({"test":super::test_key::CERTIFICATE})))
        })).route("/oauth", post(|| async { Json(json!({"access_token":"test-admin","token_type":"Bearer","expires_in":3600})) }))
        .route("/accounts", post(|State(remote): State<Arc<Remote>>, Json(body): Json<serde_json::Value>| async move {
            Json(json!({"users":[{"localId":body["localId"][0],"disabled":remote.disabled.load(Ordering::SeqCst),
                "validSince":remote.revoked_after.load(Ordering::SeqCst).to_string()}]}))
        })).route("/messages", post(external_provider)).with_state(remote.clone());
        let server = tokio::spawn(async move {
            axum::serve(listener, upstream).await.unwrap();
        });
        let config = super::Config::test_config().with_test_server(url);
        let app = super::router(Some(config.clone()), database.clone());
        Self {
            app,
            config,
            database,
            remote,
            server,
            admin,
            schema,
        }
    }
    async fn request(&self, uid: &str, key: &str) -> axum::response::Response {
        self.request_kind(uid, key, None).await
    }
    async fn request_kind(
        &self,
        uid: &str,
        key: &str,
        kind: Option<&str>,
    ) -> axum::response::Response {
        let mut input: serde_json::Value =
            serde_json::from_str(include_str!("../../examples/development-ai-input.json")).unwrap();
        if let Some(kind) = kind {
            input["request_kind"] = json!(kind);
        }
        self.app
            .clone()
            .oneshot(
                Request::post("/v1/suggestions")
                    .header("Content-Type", "application/json")
                    .header("Authorization", format!("Bearer {}", token(uid)))
                    .body(Body::from(
                        json!({"state_key":key,"input":input}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap()
    }
    async fn close(self) {
        self.server.abort();
        drop(self.app);
        self.database.close().await;
        sqlx::query(&format!("DROP SCHEMA {} CASCADE", self.schema))
            .execute(&self.admin)
            .await
            .unwrap();
        self.admin.close().await;
    }
}

async fn result(response: axum::response::Response) -> serde_json::Value {
    use http_body_util::BodyExt;
    serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes()).unwrap()
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn checker_reject_uncertain_and_structural_failure_never_return_a_candidate() {
    let fixture = Fixture::new().await;
    for (mode, expected, calls) in [
        ("reject", "rejected", 2),
        ("uncertain", "uncertain", 2),
        ("invalid", "invalid_proposal", 1),
        ("truncated", "failed", 1),
        ("refusal", "rejected", 1),
        ("tool", "rejected", 1),
    ] {
        *fixture.remote.mode.lock().unwrap() = mode.into();
        fixture.remote.calls.lock().unwrap().clear();
        let body = result(fixture.request("allowed", mode).await).await;
        assert_eq!(body["disposition"], expected);
        assert!(body["proposal"].is_null());
        assert_eq!(fixture.remote.calls.lock().unwrap().len(), calls);
    }
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn disabled_revoked_and_lookup_failure_never_spend_ai_budget() {
    let fixture = Fixture::new().await;
    fixture.remote.disabled.store(true, Ordering::SeqCst);
    assert_eq!(
        fixture.request("allowed", "disabled").await.status(),
        StatusCode::UNAUTHORIZED
    );
    fixture.remote.disabled.store(false, Ordering::SeqCst);
    fixture.remote.revoked_after.store(
        jsonwebtoken::get_current_timestamp() + 3600,
        Ordering::SeqCst,
    );
    assert_eq!(
        fixture.request("allowed", "revoked").await.status(),
        StatusCode::UNAUTHORIZED
    );
    fixture.remote.revoked_after.store(0, Ordering::SeqCst);
    let mut config = fixture.config.clone();
    config.firebase.endpoints.lookup += "/missing";
    let unavailable = super::router(Some(config), fixture.database.clone());
    let response = unavailable
        .oneshot(
            Request::post("/v1/suggestions")
                .header("Content-Type", "application/json")
                .header("Authorization", format!("Bearer {}", token("allowed")))
                .body(Body::from("{}"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    assert!(fixture.remote.calls.lock().unwrap().is_empty());
    // Revocation status is checked again, so the same cached signing key cannot bypass re-enable.
    assert_eq!(
        result(fixture.request("allowed", "enabled").await).await["disposition"],
        "accepted"
    );
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn missing_usage_stays_charged_after_restart_and_budget_rejection_never_calls_provider() {
    let mut fixture = Fixture::new().await;
    *fixture.remote.mode.lock().unwrap() = "missing_usage".into();
    for key in ["one", "two"] {
        assert_eq!(
            result(fixture.request("allowed", key).await).await["disposition"],
            "accepted"
        );
    }
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    assert_eq!(
        fixture.request("allowed", "three").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 4);
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn unconfirmed_model_with_usage_blocks_budget_after_restart() {
    for (mode, calls) in [("wrong_generate_model", 1), ("wrong_check_model", 2)] {
        let mut fixture = Fixture::new().await;
        *fixture.remote.mode.lock().unwrap() = mode.into();
        assert_eq!(
            result(fixture.request("allowed", "wrong-model").await).await["disposition"],
            "failed"
        );
        assert_eq!(fixture.remote.calls.lock().unwrap().len(), calls);
        *fixture.remote.mode.lock().unwrap() = String::new();
        fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
        assert_eq!(
            fixture.request("allowed", "after-restart").await.status(),
            StatusCode::TOO_MANY_REQUESTS
        );
        assert_eq!(fixture.remote.calls.lock().unwrap().len(), calls);
        fixture.close().await;
    }
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn active_identity_is_user_scoped_and_disconnect_stops_checker_without_refunding_unknown_cost()
 {
    use http_body_util::BodyExt;
    let mut fixture = Fixture::new().await;
    fixture.config.budget_limit = 42_000;
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    fixture.remote.delay_ms.store(5_000, Ordering::SeqCst);
    let response = fixture.request("allowed", "same-state").await;
    // A duplicate cannot start even from another router instance.
    let duplicate = fixture.request("allowed", "same-state").await;
    assert_eq!(duplicate.status(), StatusCode::CONFLICT);
    assert_eq!(
        fixture.request("other", "same-state").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    let pending = tokio::spawn(async move { response.into_body().collect().await });
    for _ in 0..200 {
        if !fixture.remote.calls.lock().unwrap().is_empty() {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(5)).await;
    }
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 1);
    pending.abort();
    let _ = pending.await;
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    // Cancellation retains the committed two-call reservation.
    assert_eq!(
        fixture.request("allowed", "new-state").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 1);
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn allowed_user_receives_only_independently_checked_proposal_and_usage() {
    use http_body_util::BodyExt;
    let fixture = Fixture::new().await;
    let response = fixture.request("allowed", "1:0").await;
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let body: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(body["disposition"], "accepted");
    assert_eq!(body["proposal"]["action"], "펜 하나 옮기기");
    assert_eq!(body["usage"][0]["input_tokens"], 11);
    assert!(body["elapsed_ms"].as_u64().is_some());
    let calls = fixture.remote.calls.lock().unwrap().clone();
    assert_eq!(calls.len(), 2);
    for (index, request) in calls.into_iter().enumerate() {
        assert_eq!(request["model"], "claude-haiku-5-5");
        assert_eq!(request["tools"], json!([]));
        assert_eq!(request["output_config"]["effort"], "xhigh");
        assert_eq!(request["thinking"]["type"], "adaptive");
        assert_eq!(request["service_tier"], "standard_only");
        assert_eq!(request["messages"].as_array().unwrap().len(), 1);
        assert_eq!(request["messages"][0]["role"], "user");
        assert_eq!(request["max_tokens"], 1000);
        assert_eq!(request["stream"], false);
        assert!(request.get("store").is_none());
        assert!(request.get("cache_control").is_none());
        assert_eq!(
            request["system"],
            crate::development_ai::model_instructions(if index == 0 {
                "generate"
            } else {
                "check"
            })
            .unwrap()
        );
        if index == 0 {
            assert_eq!(
                request["output_config"]["format"]["schema"],
                crate::development_ai::generation_schema(None)
            );
        }
        if index == 1 {
            assert_eq!(
                request["output_config"]["format"]["schema"]["properties"]["criteria"]["items"],
                json!({"type":"integer","enum":[1,2,3,4,5]})
            );
        }
    }
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn request_status_contract_and_schema_match_through_real_database_and_http() {
    let fixture = Fixture::new().await;
    for (index, (kind, mode, expected, calls)) in [
        ("goal_preparation", "", "invalid_proposal", 1),
        ("goal_preparation", "minimum", "invalid_proposal", 1),
        ("goal_preparation", "goal_summary", "accepted", 2),
        ("goal_preparation", "need_info", "accepted", 2),
        ("smaller", "no_action", "invalid_proposal", 1),
        ("smaller", "minimum", "accepted", 2),
        ("replacement", "no_action", "accepted", 2),
        ("next_action", "goal_summary", "invalid_proposal", 1),
    ]
    .into_iter()
    .enumerate()
    {
        *fixture.remote.mode.lock().unwrap() = mode.into();
        fixture.remote.calls.lock().unwrap().clear();
        let body = result(
            fixture
                .request_kind("allowed", &format!("status-{index}"), Some(kind))
                .await,
        )
        .await;
        assert_eq!(body["disposition"], expected, "{kind}/{mode}");
        assert_eq!(body["proposal"].is_null(), expected != "accepted");
        let sent = fixture.remote.calls.lock().unwrap().clone();
        assert_eq!(sent.len(), calls);
        assert_eq!(
            sent[0]["output_config"]["format"]["schema"],
            crate::development_ai::generation_schema(Some(kind))
        );
        if calls == 2 {
            let checked: serde_json::Value =
                serde_json::from_str(sent[1]["messages"][0]["content"].as_str().unwrap()).unwrap();
            let original: serde_json::Value =
                serde_json::from_str(sent[0]["messages"][0]["content"].as_str().unwrap()).unwrap();
            assert_eq!(checked["original_request"], original);
            assert_eq!(checked["candidate"], body["proposal"]);
        }
    }
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn cache_tokens_beyond_full_context_block_budget_after_restart() {
    let mut fixture = Fixture::new().await;
    *fixture.remote.mode.lock().unwrap() = "cache_overrun".into();
    assert_eq!(
        result(fixture.request("allowed", "cache-overrun").await).await["disposition"],
        "failed"
    );
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 1);
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    assert_eq!(
        fixture.request("allowed", "after-restart").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 1);
    fixture.close().await;
}

fn token(uid: &str) -> String {
    let now = jsonwebtoken::get_current_timestamp();
    let mut header = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
    header.kid = Some("test".into());
    jsonwebtoken::encode(
        &header,
        &json!({"sub":uid,"aud":"test-project",
        "iss":"https://securetoken.google.com/test-project","iat":now,"exp":now+3600,
        "auth_time":now,"firebase":{"sign_in_provider":"anonymous"}}),
        &jsonwebtoken::EncodingKey::from_rsa_pem(super::test_key::PRIVATE.as_bytes()).unwrap(),
    )
    .unwrap()
}

#[tokio::test]
async fn wrong_project_signature_algorithm_expiry_and_subject_never_authorize() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        axum::serve(
            listener,
            Router::new().route(
                "/keys",
                get(|| async {
                    (
                        [("Cache-Control", "max-age=300")],
                        Json(json!({"test":super::test_key::CERTIFICATE})),
                    )
                }),
            ),
        )
        .await
        .unwrap();
    });
    let database = PgPoolOptions::new()
        .connect_lazy("postgres://unused:unused@127.0.0.1:1/unused")
        .unwrap();
    let app = super::router(
        Some(super::Config::test_config().with_test_server(url)),
        database,
    );
    let now = jsonwebtoken::get_current_timestamp();
    let baseline = json!({"sub":"allowed","aud":"test-project","iss":"https://securetoken.google.com/test-project",
        "iat":now,"exp":now+3600,"auth_time":now,"firebase":{"sign_in_provider":"anonymous"}});
    for (field, value) in [
        ("aud", json!("wrong-project")),
        ("aud", json!(["test-project"])),
        ("iss", json!("https://securetoken.google.com/wrong")),
        ("exp", json!(now - 1)),
        ("iat", json!(now + 3600)),
        ("auth_time", json!(now + 3600)),
        ("sub", json!("")),
        ("user_id", json!("other")),
    ] {
        let mut claims = baseline.clone();
        claims[field] = value;
        let mut head = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
        head.kid = Some("test".into());
        let jwt = jsonwebtoken::encode(
            &head,
            &claims,
            &jsonwebtoken::EncodingKey::from_rsa_pem(super::test_key::PRIVATE.as_bytes()).unwrap(),
        )
        .unwrap();
        let response = app
            .clone()
            .oneshot(
                Request::post("/v1/suggestions")
                    .header("Content-Type", "application/json")
                    .header("Authorization", format!("Bearer {jwt}"))
                    .body(Body::from("{}"))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{field}");
    }
    let mut head = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::HS256);
    head.kid = Some("test".into());
    let jwt = jsonwebtoken::encode(
        &head,
        &baseline,
        &jsonwebtoken::EncodingKey::from_secret(b"not-an-RSA-key"),
    )
    .unwrap();
    let response = app
        .oneshot(
            Request::post("/v1/suggestions")
                .header("Content-Type", "application/json")
                .header("Authorization", format!("Bearer {jwt}"))
                .body(Body::from("{}"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    server.abort();
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn concurrent_last_balance_is_reserved_once_and_usage_ceiling_overrun_exhausts_budget() {
    let mut fixture = Fixture::new().await;
    fixture.config.budget_limit = 42_000;
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    let (a, b) = tokio::join!(
        fixture.request("allowed", "one"),
        fixture.request("other", "two")
    );
    let response = if a.status() == StatusCode::OK {
        assert_eq!(b.status(), StatusCode::TOO_MANY_REQUESTS);
        a
    } else {
        assert_eq!(a.status(), StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(b.status(), StatusCode::OK);
        b
    };
    assert_eq!(result(response).await["disposition"], "accepted");
    fixture.config.budget_limit = 84_000;
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    *fixture.remote.mode.lock().unwrap() = "overrun".into();
    assert_eq!(
        result(fixture.request("allowed", "overrun").await).await["disposition"],
        "failed"
    );
    assert_eq!(
        fixture.request("allowed", "blocked").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn overrun_remains_blocked_after_other_instances_refund_and_restart() {
    let mut fixture = Fixture::new().await;
    fixture.config.budget_limit = 128_000;
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    let overrun = fixture.request("allowed", "overrun").await;
    let normal = fixture.request("other", "normal").await;
    // A second API instance has its own capacity, but shares the durable monthly budget.
    let mut replica = super::router(Some(fixture.config.clone()), fixture.database.clone());
    std::mem::swap(&mut replica, &mut fixture.app);
    let other_normal = fixture.request("other", "other-normal").await;
    std::mem::swap(&mut replica, &mut fixture.app);
    assert_eq!(overrun.status(), StatusCode::OK);
    assert_eq!(normal.status(), StatusCode::OK);
    assert_eq!(other_normal.status(), StatusCode::OK);
    *fixture.remote.mode.lock().unwrap() = "overrun".into();
    assert_eq!(result(overrun).await["disposition"], "failed");
    *fixture.remote.mode.lock().unwrap() = String::new();
    assert_eq!(result(normal).await["disposition"], "accepted");
    assert_eq!(result(other_normal).await["disposition"], "accepted");
    drop(replica);
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    assert_eq!(
        fixture.request("allowed", "after-refund").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    // A later configuration increase cannot silently clear an overrun either.
    fixture.config.budget_limit = 256_000;
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    assert_eq!(
        fixture.request("allowed", "after-increase").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 5);
    fixture.close().await;
}

#[tokio::test]
async fn signed_user_without_permission_cannot_reach_database_or_ai() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let upstream = tokio::spawn(async move {
        axum::serve(
            listener,
            axum::Router::new().route(
                "/keys",
                axum::routing::get(|| async {
                    (
                        [("Cache-Control", "max-age=300")],
                        axum::Json(json!({"test":super::test_key::CERTIFICATE})),
                    )
                }),
            ),
        )
        .await
        .unwrap();
    });
    let database = PgPoolOptions::new()
        .connect_lazy("postgres://unused:unused@127.0.0.1:1/unused")
        .unwrap();
    let app = super::router(
        Some(super::Config::test_config().with_test_server(format!("http://{address}"))),
        database,
    );
    let response = app
        .oneshot(
            Request::post("/v1/suggestions")
                .header("Content-Type", "application/json")
                .header("Authorization", format!("Bearer {}", token("not-allowed")))
                .body(Body::from("{}"))
                .unwrap(),
        )
        .await
        .unwrap();
    upstream.abort();
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn off_user_ai_route_cannot_start_authentication_or_provider() {
    let database = PgPoolOptions::new()
        .connect_lazy("postgres://unused:unused@127.0.0.1:1/unused")
        .unwrap();
    let response = super::router(None, database)
        .oneshot(
            Request::post("/v1/suggestions")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn enabled_route_rejects_missing_or_malformed_bearer_before_database() {
    let database = PgPoolOptions::new()
        .connect_lazy("postgres://unused:unused@127.0.0.1:1/unused")
        .unwrap();
    for authorization in [None, Some("Bearer invalid"), Some("Basic invalid")] {
        let app = super::router(Some(super::Config::test_config()), database.clone());
        let mut request =
            Request::post("/v1/suggestions").header("Content-Type", "application/json");
        if let Some(value) = authorization {
            request = request.header("Authorization", value);
        }
        let response = app
            .oneshot(request.body(Body::from("{}")).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }
}

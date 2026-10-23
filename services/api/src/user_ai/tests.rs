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
    deleted: std::sync::atomic::AtomicBool,
    user_failure: std::sync::atomic::AtomicBool,
    user_mode: Mutex<String>,
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
    let generating = body["output_config"]["format"]["schema"]["properties"]
        .get("action")
        .is_some();
    let mut value = if generating {
        json!({"status": match mode.as_str() { "minimum" | "no_action" | "goal_summary" | "need_info" => mode.as_str(), _ => "action" },"action":"펜 하나 옮기기","completion_condition":"펜이 펜꽂이에 있다",
            "estimated_minutes":1,"reason":"한 물건만 옮긴다","facts":[],"reduction":"해당 없음"})
    } else {
        json!({"verdict":if mode=="reject" || mode=="uncertain" { mode.as_str() } else { "accept" },"criteria":[1,2,3,4,5],"evidence":"원본과 일치"})
    };
    if (mode == "invalid" || mode == "invalid_missing_usage") && generating {
        value["goal_completed"] = json!(true);
    }
    if mode.starts_with("notice") {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../../contracts/fixtures/insufficient-info.json"
        ))
        .unwrap();
        if generating {
            value = fixture["generated"].clone();
            for key in [
                "remaining_work",
                "preserved_completed_ids",
                "goal_completed",
                "current_action_completed",
            ] {
                value.as_object_mut().unwrap().remove(key);
            }
            match mode.as_str() {
                "notice_action" => value["action"] = json!("가짜 행동"),
                "notice_minutes" => value["estimated_minutes"] = json!(1),
                "notice_reduction" => value["reduction"] = json!("축소"),
                _ => {}
            }
        } else if let Some(id) = mode.strip_prefix("notice-case-") {
            let case = fixture["checker_cases"]
                .as_array()
                .unwrap()
                .iter()
                .find(|case| case["id"] == id)
                .unwrap();
            value = case["check"].clone();
            value.as_object_mut().unwrap().remove("reason");
        }
    }
    let fault_mode = mode.strip_prefix("notice_").unwrap_or(&mode);
    let fault = fault_mode.strip_prefix(if generating { "generate_" } else { "check_" });
    let field = if generating { "action" } else { "evidence" };
    match fault {
        Some("type") => value[field] = json!(["private-output"]),
        Some("required") => {
            value.as_object_mut().unwrap().remove(field);
        }
        Some("additional") => value["private-key"] = json!("private-output"),
        Some("owned") => {
            value[if generating {
                "remaining_work"
            } else {
                "reason"
            }] = json!("private-output")
        }
        Some("enum") => {
            value[if generating { "status" } else { "verdict" }] = json!("private-output")
        }
        Some("empty") => value[field] = json!(" "),
        Some("criteria") => value["criteria"] = json!([1, 2, 3, 4]),
        Some("empty_criteria") => value["criteria"] = json!([]),
        Some("criteria_type") => value["criteria"] = json!([1, 2, "private-output", 4, 5]),
        Some("criteria_enum") => value["criteria"] = json!([1, 2, 3, 4, 6]),
        _ => {}
    }
    let text = match fault {
        Some("syntax") => "{private-output".to_owned(),
        Some("depth") => format!("{}0{}", "[".repeat(256), "]".repeat(256)),
        Some("trailing") => format!("{} private-output", value),
        Some("duplicate") => format!(
            "{{\"{field}\":\"private-output\",{}",
            &value.to_string()[1..]
        ),
        Some("escaped_duplicate") => format!(
            "{{\"{}\":\"private-output\",{}",
            if generating {
                "actio\\u006e"
            } else {
                "evidenc\\u0065"
            },
            &value.to_string()[1..]
        ),
        Some("nested_duplicate") => format!(
            "{{\"private-key\":{{\"secret\":1,\"secret\":2}},{}",
            &value.to_string()[1..]
        ),
        _ => value.to_string(),
    };
    let mut response = json!({"type":"message","role":"assistant","model":"claude-haiku-5-5","stop_reason":"end_turn",
        "content":[{"type":"thinking","thinking":"private-thinking","signature":"test"},{"type":"text","text":text}],
        "usage":{"input_tokens":8,"output_tokens":7,"cache_read_input_tokens":3,"cache_creation_input_tokens":0,
            "output_tokens_details":{"thinking_tokens":2}}});
    if mode == "missing_usage" || mode == "invalid_missing_usage" {
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
        sqlx::query(
            "CREATE TABLE fixture_sessions (user_id TEXT PRIMARY KEY, active BOOLEAN NOT NULL)",
        )
        .execute(&database)
        .await
        .unwrap();
        for uid in [identity("allowed"), identity("other")] {
            sqlx::query("INSERT INTO fixture_sessions VALUES ($1, TRUE)")
                .bind(uid)
                .execute(&database)
                .await
                .unwrap();
        }
        sqlx::query(&format!("CREATE OR REPLACE FUNCTION smallnext_session_active(user_id TEXT,session_id TEXT) RETURNS BOOLEAN LANGUAGE SQL SECURITY INVOKER SET search_path = '' AS 'SELECT EXISTS(SELECT 1 FROM {schema}.fixture_sessions WHERE user_id = $1 AND active AND $2 = ''{SESSION}'')'"))
            .execute(&database).await.unwrap();
        let upstream = Router::new()
            .route(
                "/keys",
                get(|| async { ([("Cache-Control", "max-age=300")], Json(jwks())) }),
            )
            .route(
                "/user",
                get(
                    |State(remote): State<Arc<Remote>>, headers: axum::http::HeaderMap| async move {
                        assert_eq!(headers["apikey"], "sb_publishable_test");
                        if remote.user_failure.load(Ordering::SeqCst) {
                            return Err(StatusCode::SERVICE_UNAVAILABLE);
                        }
                        if remote.deleted.load(Ordering::SeqCst)
                            || remote.disabled.load(Ordering::SeqCst)
                        {
                            return Err(StatusCode::UNAUTHORIZED);
                        }
                        let token = headers["authorization"]
                            .to_str()
                            .unwrap()
                            .strip_prefix("Bearer ")
                            .unwrap();
                        let data =
                            jsonwebtoken::dangerous::insecure_decode::<serde_json::Value>(token)
                                .unwrap();
            let mode = remote.user_mode.lock().unwrap().clone();
            Ok(Json(json!({"id":if mode=="wrong_user" { json!(identity("other")) } else { data.claims["sub"].clone() },"is_anonymous":mode!="permanent"})))
                    },
                ),
            )
            .route("/messages", post(external_provider))
            .with_state(remote.clone());
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
        self.request_input(uid, key, input).await
    }
    async fn request_input(
        &self,
        uid: &str,
        key: &str,
        input: serde_json::Value,
    ) -> axum::response::Response {
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
#[ignore = "requires TEST_DATABASE_URL; mock auth/provider against isolated PostgreSQL"]
async fn timing_connects_mock_auth_provider_and_total_without_changing_contract() {
    let fixture = Fixture::new().await;
    fixture.remote.delay_ms.store(15, Ordering::SeqCst);
    let input: serde_json::Value =
        serde_json::from_str(include_str!("../../examples/development-ai-input.json")).unwrap();
    let body = result(
        fixture
            .app
            .clone()
            .oneshot(
                Request::post("/v1/suggestions")
                    .header("Content-Type", "application/json")
                    .header("Authorization", format!("Bearer {}", token("allowed")))
                    .header("X-Smallnext-Timing", "22222222-2222-4222-8222-222222222222")
                    .body(Body::from(
                        json!({"state_key":"timing-test", "input":input}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap(),
    )
    .await;
    assert_eq!(body["disposition"], "accepted");
    let timing = &body["_timing"];
    if cfg!(debug_assertions) {
        assert_eq!(timing["run_id"], "22222222-2222-4222-8222-222222222222");
        assert!(timing["generate_ms"].as_f64().unwrap() >= 15.0);
        assert!(timing["check_ms"].as_f64().unwrap() >= 15.0);
        assert!(
            timing["total_ms"].as_f64().unwrap()
                >= timing["generate_ms"].as_f64().unwrap() + timing["check_ms"].as_f64().unwrap()
        );
    } else {
        assert!(body.get("_timing").is_none());
    }
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 2);
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn malformed_decisions_stop_at_the_failing_role_without_retry() {
    let logs = LogBuffer::default();
    let writer = logs.clone();
    // Keep one process-wide collector for concurrent HTTP work and callsite registration.
    tracing::subscriber::set_global_default(
        tracing_subscriber::fmt()
            .without_time()
            .with_ansi(false)
            .with_writer(move || writer.clone())
            .finish(),
    )
    .unwrap();
    let fixture = Fixture::new().await;
    for role in ["generate", "check"] {
        for fault in [
            "duplicate",
            "escaped_duplicate",
            "nested_duplicate",
            "depth",
            "trailing",
            "syntax",
            "type",
            "required",
            "additional",
            "owned",
            "enum",
            "empty",
        ] {
            let mode = format!("{role}_{fault}");
            *fixture.remote.mode.lock().unwrap() = mode.clone();
            fixture.remote.calls.lock().unwrap().clear();
            logs.0.lock().unwrap().clear();
            let body = result(fixture.request("allowed", &mode).await).await;
            assert_eq!(
                body["disposition"],
                if role == "generate" {
                    "invalid_proposal"
                } else {
                    "failed"
                },
                "{mode}"
            );
            let log = String::from_utf8(logs.0.lock().unwrap().clone()).unwrap();
            assert!(!log.contains("private-"), "{mode}: {log}");
            {
                assert!(log.contains("invalid_ai_decision"), "{mode}: {log}");
                assert!(log.contains(&format!("role=\"{role}\"")), "{mode}: {log}");
                let classification = if ["syntax", "depth", "trailing"].contains(&fault) {
                    "json_syntax"
                } else if fault == "owned" {
                    "additional"
                } else if fault == "empty" {
                    "nonblank"
                } else if fault.contains("duplicate") {
                    "duplicate_key"
                } else {
                    fault
                };
                assert!(
                    log.contains(&format!("kind=\"{classification}\"")),
                    "{mode}: {log}"
                );
            }
            assert!(body["proposal"].is_null());
            assert_eq!(
                fixture.remote.calls.lock().unwrap().len(),
                if role == "generate" { 1 } else { 2 },
                "{mode}"
            );
        }
    }
    fixture.close().await;
}

#[derive(Clone, Default)]
struct LogBuffer(Arc<Mutex<Vec<u8>>>);
impl std::io::Write for LogBuffer {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn checker_requires_all_five_criteria_and_nonblank_grounded_evidence() {
    let fixture = Fixture::new().await;
    for mode in [
        "check_criteria",
        "check_empty_criteria",
        "check_criteria_type",
        "check_criteria_enum",
        "check_empty",
    ] {
        *fixture.remote.mode.lock().unwrap() = mode.into();
        fixture.remote.calls.lock().unwrap().clear();
        let body = result(fixture.request("allowed", mode).await).await;
        assert_eq!(body["disposition"], "failed", "{mode}");
        assert!(body["proposal"].is_null());
        assert_eq!(fixture.remote.calls.lock().unwrap().len(), 2);
    }
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn invalid_decision_with_unknown_usage_keeps_conservative_charge_after_restart() {
    let mut fixture = Fixture::new().await;
    fixture.config.budget_limit = 42_000;
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    *fixture.remote.mode.lock().unwrap() = "invalid_missing_usage".into();
    let body = result(fixture.request("allowed", "invalid-unknown-usage").await).await;
    assert_eq!(body["disposition"], "invalid_proposal");
    assert!(body["proposal"].is_null());
    assert_eq!(body["usage"], json!([]));
    fixture.app = super::router(Some(fixture.config.clone()), fixture.database.clone());
    assert_eq!(
        fixture.request("allowed", "after-restart").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 1);
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn decisions_preserve_original_state_and_specialize_only_smaller_questions() {
    let fixture = Fixture::new().await;
    for (kind, mode, specialized) in [
        ("smaller", "need_info", true),
        ("first_action", "need_info", false),
        ("smaller", "minimum", false),
        ("replacement", "no_action", false),
    ] {
        *fixture.remote.mode.lock().unwrap() = mode.into();
        fixture.remote.calls.lock().unwrap().clear();
        let mut input: serde_json::Value =
            serde_json::from_str(include_str!("../../examples/development-ai-input.json")).unwrap();
        input["request_kind"] = json!(kind);
        input["available_minutes"] = json!(2.0);
        input["remaining_work"] = json!(["남은 작업", "보류 작업"]);
        input["completed_ids"] = json!(["completed-1", "completed-2"]);
        input["available"] = json!(["보류 작업은 보류 상태다", "완료 작업은 완료했다"]);
        let body = result(
            fixture
                .request_input("allowed", &format!("{kind}-{mode}"), input.clone())
                .await,
        )
        .await;
        assert_eq!(body["disposition"], "accepted");
        assert!(
            body["proposal"].get("facts").is_none() && body["proposal"].get("reduction").is_none()
        );
        assert_eq!(
            body["proposal"]["remaining_work"],
            json!(["남은 작업", "보류 작업"])
        );
        assert_eq!(
            body["proposal"]["preserved_completed_ids"],
            json!(["completed-1", "completed-2"])
        );
        assert_eq!(body["proposal"]["goal_completed"], false);
        assert_eq!(body["proposal"]["current_action_completed"], false);
        let calls = fixture.remote.calls.lock().unwrap().clone();
        assert_eq!(calls.len(), 2);
        let prompt = calls[1]["system"].as_str().unwrap();
        assert_eq!(prompt.starts_with("Independently check all five mandatory criteria for this need_info question on a smaller request."), specialized);
        for rule in [
            "Eligibility before selection:",
            "Five mandatory criteria,",
            "repeated failure",
            "Also stop smaller",
            "Host-verified literal preservation:",
            "goal_incomplete\":true",
            "completed_ids_exact\":true",
            "remaining_work_exact\":true",
            "current_action_incomplete\":true",
        ] {
            assert!(prompt.contains(rule), "missing {rule}");
        }
        assert_eq!(prompt.contains("- goal_preparation permits"), !specialized);
        assert_eq!(prompt.contains("- no_action uses"), !specialized);
        let checked: serde_json::Value =
            serde_json::from_str(calls[1]["messages"][0]["content"].as_str().unwrap()).unwrap();
        assert_eq!(checked["original_request"], input);
        assert_eq!(checked["candidate"], grounded(&body["proposal"]));
    }
    fixture.close().await;
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
    sqlx::query("UPDATE fixture_sessions SET active=FALSE")
        .execute(&fixture.database)
        .await
        .unwrap();
    assert_eq!(
        fixture.request("allowed", "revoked").await.status(),
        StatusCode::UNAUTHORIZED
    );
    sqlx::query("UPDATE fixture_sessions SET active=TRUE")
        .execute(&fixture.database)
        .await
        .unwrap();
    fixture.remote.deleted.store(true, Ordering::SeqCst);
    assert_eq!(
        fixture.request("allowed", "deleted").await.status(),
        StatusCode::UNAUTHORIZED
    );
    fixture.remote.deleted.store(false, Ordering::SeqCst);
    fixture.remote.user_failure.store(true, Ordering::SeqCst);
    assert_eq!(
        fixture.request("allowed", "lookup-failed").await.status(),
        StatusCode::SERVICE_UNAVAILABLE
    );
    fixture.remote.user_failure.store(false, Ordering::SeqCst);
    let mut config = fixture.config.clone();
    config.supabase.endpoints.user += "/missing";
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
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    assert!(fixture.remote.calls.lock().unwrap().is_empty());
    let charged: Option<i64> = sqlx::query_scalar("SELECT charged_micro_usd FROM ai_budget")
        .fetch_optional(&fixture.database)
        .await
        .unwrap();
    assert_eq!(charged, None);
    // Revocation status is checked again, so the same cached signing key cannot bypass re-enable.
    assert_eq!(
        result(fixture.request("allowed", "enabled").await).await["disposition"],
        "accepted"
    );
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn current_user_mismatch_and_session_lookup_failure_never_call_provider() {
    let fixture = Fixture::new().await;
    for mode in ["wrong_user", "permanent"] {
        *fixture.remote.user_mode.lock().unwrap() = mode.into();
        assert_eq!(
            fixture.request("allowed", mode).await.status(),
            StatusCode::UNAUTHORIZED
        );
    }
    fixture.remote.user_mode.lock().unwrap().clear();
    let mut payload = claims("allowed");
    payload["session_id"] = json!("44444444-4444-4444-8444-444444444444");
    let mut head = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
    head.kid = Some("test".into());
    let token = jsonwebtoken::encode(
        &head,
        &payload,
        &jsonwebtoken::EncodingKey::from_rsa_pem(super::test_key::PRIVATE.as_bytes()).unwrap(),
    )
    .unwrap();
    let response = fixture
        .app
        .clone()
        .oneshot(
            Request::post("/v1/suggestions")
                .header("Content-Type", "application/json")
                .header("Authorization", format!("Bearer {token}"))
                .body(Body::from("{}"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    sqlx::query("DROP FUNCTION smallnext_session_active(TEXT,TEXT)")
        .execute(&fixture.database)
        .await
        .unwrap();
    assert_eq!(
        fixture
            .request("allowed", "session-lookup-failed")
            .await
            .status(),
        StatusCode::SERVICE_UNAVAILABLE
    );
    assert!(fixture.remote.calls.lock().unwrap().is_empty());
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn es256_anonymous_user_passes_current_account_and_session_checks() {
    let fixture = Fixture::new().await;
    let mut head = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::ES256);
    head.kid = Some("test-ec".into());
    let token = jsonwebtoken::encode(
        &head,
        &claims("allowed"),
        &jsonwebtoken::EncodingKey::from_ec_pem(super::test_key::EC_PRIVATE.as_bytes()).unwrap(),
    )
    .unwrap();
    let input: serde_json::Value =
        serde_json::from_str(include_str!("../../examples/development-ai-input.json")).unwrap();
    let response = fixture
        .app
        .clone()
        .oneshot(
            Request::post("/v1/suggestions")
                .header("Content-Type", "application/json")
                .header("Authorization", format!("Bearer {token}"))
                .body(Body::from(
                    json!({"state_key":"ec-session", "input":input}).to_string(),
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(result(response).await["disposition"], "accepted");
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 2);
    fixture.close().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; runtime role against real isolated PostgreSQL"]
async fn runtime_role_reserves_settles_and_blocks_budget_through_http() {
    let mut fixture = Fixture::new().await;
    // Only this synthetic session fixture needs a grant; managed Auth stays inaccessible.
    sqlx::query("GRANT SELECT ON fixture_sessions TO smallnext_api")
        .execute(&fixture.database)
        .await
        .unwrap();
    let url = std::env::var("TEST_DATABASE_URL").unwrap();
    let options: sqlx::postgres::PgConnectOptions = url.parse().unwrap();
    let runtime = PgPoolOptions::new()
        .max_connections(5)
        .connect_with(options.options([
            ("search_path", fixture.schema.as_str()),
            ("role", "smallnext_api"),
        ]))
        .await
        .unwrap();
    fixture.app = super::router(Some(fixture.config.clone()), runtime.clone());
    assert_eq!(
        result(fixture.request("allowed", "runtime-accepted").await).await["disposition"],
        "accepted"
    );
    let charged: i64 = sqlx::query_scalar("SELECT charged_micro_usd FROM ai_budget")
        .fetch_one(&runtime)
        .await
        .unwrap();
    assert!(charged > 0 && charged < fixture.config.budget_limit);
    *fixture.remote.mode.lock().unwrap() = "overrun".into();
    assert_eq!(
        result(fixture.request("allowed", "runtime-overrun").await).await["disposition"],
        "failed"
    );
    assert_eq!(
        fixture.request("allowed", "runtime-blocked").await.status(),
        StatusCode::TOO_MANY_REQUESTS
    );
    assert_eq!(fixture.remote.calls.lock().unwrap().len(), 3);
    assert!(
        sqlx::query("SELECT * FROM app_metadata")
            .fetch_all(&runtime)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("SELECT * FROM _sqlx_migrations")
            .fetch_all(&runtime)
            .await
            .is_err()
    );
    runtime.close().await;
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
    assert!(body.get("_timing").is_none());
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
        let schema = &request["output_config"]["format"]["schema"];
        assert_eq!(
            schema["properties"].as_object().unwrap().len(),
            if index == 0 { 7 } else { 3 }
        );
        assert_eq!(schema["additionalProperties"], false);
        assert!(
            request["system"]
                .as_str()
                .unwrap()
                .contains("Five mandatory criteria,")
        );
        assert!(
            request["system"]
                .as_str()
                .unwrap()
                .contains("Eligibility before selection:")
        );
        if index == 0 {
            assert_eq!(
                request["output_config"]["format"]["schema"],
                crate::suggestion::compact::request(crate::suggestion::Role::Generate, &json!({}))
                    .1
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
            crate::suggestion::compact::request(
                crate::suggestion::Role::Generate,
                &json!({"request_kind": kind})
            )
            .1
        );
        if calls == 2 {
            let checked: serde_json::Value =
                serde_json::from_str(sent[1]["messages"][0]["content"].as_str().unwrap()).unwrap();
            let original: serde_json::Value =
                serde_json::from_str(sent[0]["messages"][0]["content"].as_str().unwrap()).unwrap();
            assert_eq!(checked["original_request"], original);
            assert_eq!(checked["candidate"], grounded(&body["proposal"]));
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

const SESSION: &str = "33333333-3333-4333-8333-333333333333";
pub(super) fn identity(uid: &str) -> String {
    match uid {
        "allowed" => "11111111-1111-4111-8111-111111111111".into(),
        "other" => "22222222-2222-4222-8222-222222222222".into(),
        _ => "99999999-9999-4999-8999-999999999999".into(),
    }
}
fn jwks() -> serde_json::Value {
    let key = jsonwebtoken::EncodingKey::from_rsa_pem(super::test_key::PRIVATE.as_bytes()).unwrap();
    let mut jwk =
        jsonwebtoken::jwk::Jwk::from_encoding_key(&key, jsonwebtoken::Algorithm::RS256).unwrap();
    jwk.common.key_id = Some("test".into());
    let signing =
        jsonwebtoken::EncodingKey::from_ec_pem(super::test_key::EC_PRIVATE.as_bytes()).unwrap();
    let mut ec =
        jsonwebtoken::jwk::Jwk::from_encoding_key(&signing, jsonwebtoken::Algorithm::ES256)
            .unwrap();
    ec.common.key_id = Some("test-ec".into());
    json!({"keys":[jwk, ec]})
}
fn claims(uid: &str) -> serde_json::Value {
    let now = jsonwebtoken::get_current_timestamp();
    json!({"sub":identity(uid),"aud":"authenticated", "iss":"https://test-project.supabase.co/auth/v1",
        "iat":now,"exp":now+3600,"role":"authenticated","is_anonymous":true,"session_id":SESSION})
}
fn token(uid: &str) -> String {
    let mut header = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::RS256);
    header.kid = Some("test".into());
    jsonwebtoken::encode(
        &header,
        &claims(uid),
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
                get(|| async { ([("Cache-Control", "max-age=300")], Json(jwks())) }),
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
    let baseline = claims("allowed");
    for (field, value) in [
        ("aud", json!("wrong-project")),
        ("aud", json!(["authenticated"])),
        ("iss", json!("https://securetoken.google.com/wrong")),
        ("exp", json!(now - 1)),
        ("iat", json!(now + 3600)),
        ("nbf", json!(now + 3600)),
        ("is_anonymous", json!(false)),
        ("role", json!("anon")),
        ("session_id", json!("bad-session")),
        ("sub", json!("")),
        ("sub", json!("not-a-uuid")),
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
                    ([("Cache-Control", "max-age=300")], axum::Json(jwks()))
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

/// The checker sees the app proposal plus the mock's grounding; the app never does.
fn grounded(proposal: &serde_json::Value) -> serde_json::Value {
    let mut candidate = proposal.clone();
    candidate["facts"] = json!([]);
    candidate["reduction"] = json!("해당 없음");
    candidate
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL; HTTP against real isolated PostgreSQL"]
async fn insufficient_info_crosses_http_with_independent_checks_and_no_failure_conversion() {
    let fixture = Fixture::new().await;
    let shared: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../contracts/fixtures/insufficient-info.json"
    ))
    .unwrap();
    for kind in ["first_action", "next_action", "smaller", "replacement"] {
        *fixture.remote.mode.lock().unwrap() = "notice".into();
        fixture.remote.calls.lock().unwrap().clear();
        let mut input = shared["input"].clone();
        input["request_kind"] = json!(kind);
        let response = result(fixture.request_input("allowed", kind, input.clone()).await).await;
        assert_eq!(response["disposition"], "accepted");
        let proposal: crate::suggestion::Proposal =
            serde_json::from_value(response["proposal"].clone()).unwrap();
        assert_eq!(
            proposal,
            serde_json::from_value(shared["response"]["proposal"].clone()).unwrap()
        );
        assert!(
            response["proposal"].get("facts").is_none()
                && response["proposal"].get("reduction").is_none()
        );
        let calls = fixture.remote.calls.lock().unwrap();
        assert_eq!(calls.len(), 2);
        let checked: serde_json::Value =
            serde_json::from_str(calls[1]["messages"][0]["content"].as_str().unwrap()).unwrap();
        assert_eq!(checked["original_request"], input);
        assert_eq!(checked["candidate"]["reduction"], "");
    }
    for case in shared["checker_cases"].as_array().unwrap() {
        *fixture.remote.mode.lock().unwrap() =
            format!("notice-case-{}", case["id"].as_str().unwrap());
        fixture.remote.calls.lock().unwrap().clear();
        let response = result(
            fixture
                .request_input(
                    "allowed",
                    case["id"].as_str().unwrap(),
                    case["input"].clone(),
                )
                .await,
        )
        .await;
        assert_eq!(response["disposition"], case["expected"], "{}", case["id"]);
        assert_eq!(
            response["proposal"].is_null(),
            case["expected"] != "accepted"
        );
        assert_eq!(fixture.remote.calls.lock().unwrap().len(), 2);
    }
    for (mode, expected, calls) in [
        ("notice_action", "invalid_proposal", 1),
        ("notice_minutes", "invalid_proposal", 1),
        ("notice_reduction", "invalid_proposal", 1),
        ("notice_check_type", "failed", 2),
    ] {
        *fixture.remote.mode.lock().unwrap() = mode.into();
        fixture.remote.calls.lock().unwrap().clear();
        let response = result(
            fixture
                .request_input("allowed", mode, shared["input"].clone())
                .await,
        )
        .await;
        assert_eq!(response["disposition"], expected);
        assert!(response["proposal"].is_null());
        assert_eq!(fixture.remote.calls.lock().unwrap().len(), calls);
    }
    fixture.close().await;
}

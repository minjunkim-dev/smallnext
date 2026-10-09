use super::*;

fn input() -> AiInput {
    serde_json::from_str(include_str!("../../examples/development-ai-input.json")).unwrap()
}

fn proposal() -> Proposal {
    Proposal {
        status: ProposalStatus::Action,
        action: "파란 펜 하나를 펜꽂이에 넣으세요.".into(),
        completion_condition: "파란 펜이 펜꽂이에 있다.".into(),
        estimated_minutes: 1.0,
        reason: "책상 왼쪽의 물건 하나를 치웁니다.".into(),
        remaining_work: input().remaining_work,
        goal_completed: false,
        current_action_completed: false,
        preserved_completed_ids: vec![],
    }
}

#[test]
fn request_status_contract() {
    for kind in [
        None,
        Some("goal_preparation"),
        Some("first_action"),
        Some("next_action"),
        Some("smaller"),
        Some("replacement"),
    ] {
        for status in [
            ProposalStatus::Action,
            ProposalStatus::NeedInfo,
            ProposalStatus::Minimum,
            ProposalStatus::GoalSummary,
            ProposalStatus::NoAction,
        ] {
            let mut data = input();
            data.request_kind = kind.map(str::to_owned);
            let mut candidate = proposal();
            candidate.status = status.clone();
            let allowed = match kind {
                Some("goal_preparation") => matches!(
                    status,
                    ProposalStatus::GoalSummary | ProposalStatus::NeedInfo
                ),
                Some("replacement") => status != ProposalStatus::GoalSummary,
                _ => matches!(
                    status,
                    ProposalStatus::Action | ProposalStatus::NeedInfo | ProposalStatus::Minimum
                ),
            };
            assert_eq!(
                validate_proposal(&data, &candidate).is_ok(),
                allowed,
                "{kind:?}: {status:?}"
            );
            let schema = generation_schema(kind);
            assert_eq!(
                schema["properties"]["status"]["enum"]
                    .as_array()
                    .unwrap()
                    .contains(&json!(status)),
                allowed,
                "schema {kind:?}: {status:?}"
            );
        }
    }
}

#[test]
fn input_contract_rejects_missing_scope_invalid_kinds_and_time() {
    assert!(validate_input(&input()).is_ok());
    for field in ["goal", "user_request", "current_blocker", "request_kind"] {
        let mut data = input();
        match field {
            "goal" => data.goal = " ".into(),
            "user_request" => data.user_request = " ".into(),
            "current_blocker" => data.current_blocker = "x".repeat(2049),
            _ => data.request_kind = Some("unsupported".into()),
        }
        assert_eq!(
            validate_input(&data),
            Err(Disposition::InvalidInput),
            "{field}"
        );
    }
    for minutes in [-1.0, f64::NAN, f64::INFINITY] {
        let mut data = input();
        data.available_minutes = minutes;
        assert_eq!(validate_input(&data), Err(Disposition::InvalidInput));
    }
    let mut data = input();
    data.available_minutes = 0.0;
    assert!(validate_input(&data).is_ok());
}

#[test]
fn candidate_preserves_exact_scope_ids_and_incomplete_state() {
    let mut data = input();
    data.remaining_work = vec!["첫 범위".into(), "둘째 범위".into()];
    data.completed_ids = vec!["done-1".into(), "done-2".into()];
    let mut good = proposal();
    good.remaining_work = data.remaining_work.clone();
    good.preserved_completed_ids = data.completed_ids.clone();
    assert!(validate_proposal(&data, &good).is_ok());
    for field in [
        "action",
        "completion_condition",
        "reason",
        "remaining_work",
        "preserved_completed_ids",
        "goal_completed",
        "current_action_completed",
        "estimated_minutes",
    ] {
        let mut value = json!(good);
        value[field] = match field {
            "remaining_work" => json!(["둘째 범위", "첫 범위"]),
            "preserved_completed_ids" => json!(["done-2", "done-1"]),
            "goal_completed" | "current_action_completed" => json!(true),
            "estimated_minutes" => json!(data.available_minutes + 1.0),
            _ => json!("  "),
        };
        let candidate = serde_json::from_value(value).unwrap();
        assert_eq!(
            validate_proposal(&data, &candidate),
            Err(Disposition::InvalidProposal),
            "{field}"
        );
    }
    for minutes in [-1.0, f64::NAN, f64::INFINITY] {
        good.estimated_minutes = minutes;
        assert_eq!(
            validate_proposal(&data, &good),
            Err(Disposition::InvalidProposal)
        );
    }
}

#[test]
fn check_response_contract_never_promotes_missing_or_invalid_evidence() {
    let good = json!({"verdict":"accept","criteria":[1,2,3,4,5],"evidence":"원본과 후보 인용", "reason":"다섯 기준과 일치"});
    assert_eq!(validate_check(good.clone()), Ok(()));
    for (field, value) in [
        ("evidence", json!(" ")),
        ("reason", json!("")),
        ("criteria", json!([])),
        ("criteria", json!([1, 2, 3, 4])),
        ("criteria", json!([1, 2, 3, 4, 6])),
        ("verdict", json!("unsupported")),
        ("extra", json!(true)),
    ] {
        let mut check = good.clone();
        check[field] = value;
        assert_eq!(validate_check(check), Err(Disposition::Failed), "{field}");
    }
    for (verdict, expected) in [
        ("reject", Disposition::Rejected),
        ("uncertain", Disposition::Uncertain),
    ] {
        let mut check = good.clone();
        check["verdict"] = json!(verdict);
        check["criteria"] = json!([1]);
        assert_eq!(validate_check(check), Err(expected));
    }
}

fn events(value: &Value) -> Vec<u8> {
    format!(
        "{}\n{}\n",
        json!({"type":"item.completed","item":{"type":"agent_message","text":value.to_string()}}),
        json!({"type":"turn.completed"})
    )
    .into_bytes()
}

#[test]
fn incomplete_tool_and_ambiguous_results_fail_closed() {
    let good = events(&json!({"ok":true}));
    assert!(parse_events(&good).is_ok());
    let notice = json!({"type":"item.completed","item":{"type":"error","message":"Exceeded skills context budget. All skill descriptions were removed and 478 additional skills were not included in the model-visible skills list."}});
    assert!(parse_events(&[format!("{notice}\n").into_bytes(), good.clone()].concat()).is_ok());
    assert!(!empty_skills_notice(
        &json!({"message":"Exceeded skills context budget. Some descriptions were removed."})
    ));
    let incomplete = good.split(|b| *b == b'\n').next().unwrap();
    assert_eq!(parse_events(incomplete), Err(Disposition::Failed));
    for bad in [
        b"not json\n".to_vec(),
        vec![],
        b"{\"type\":\"item.completed\",\"item\":{\"type\":\"command_execution\"}}\n".to_vec(),
        [good.clone(), good.clone()].concat(),
        [good, b"{\"type\":\"turn.failed\"}\n".to_vec()].concat(),
    ] {
        assert_eq!(parse_events(&bad), Err(Disposition::Failed));
    }
}

#[cfg(unix)]
struct Fixture {
    dir: Workspace,
    ai: SubscriptionAi,
}
#[cfg(unix)]
impl Fixture {
    fn new(candidate: Value, check: Value, delay: bool) -> Self {
        use std::os::unix::fs::PermissionsExt;
        let dir = Workspace::new("generate", None).unwrap();
        let executable = dir.0.join("fake-codex");
        std::fs::write(dir.0.join("candidate.json"), candidate.to_string()).unwrap();
        std::fs::write(dir.0.join("check.json"), check.to_string()).unwrap();
        let script = r#"#!/usr/bin/env python3
import json, os, pathlib, sys, time
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
schema = json.loads(pathlib.Path(args[args.index('--output-schema')+1]).read_text())
role = 'check' if 'verdict' in schema['properties'] else 'candidate'
payload = json.load(sys.stdin)
with (root/'calls.jsonl').open('a') as log:
    log.write(json.dumps({'role':role,'payload':payload,'schema':schema,'system':(pathlib.Path.cwd()/'system.md').read_text(),'args':args,'pid':os.getpid(),'keys':[k for k in ['OPENAI_API_KEY','CODEX_API_KEY','OPENAI_BASE_URL','GH_TOKEN','GITHUB_TOKEN','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN'] if k in os.environ]})+'\n')
if (root/'mode').exists():
    mode = (root/'mode').read_text()
    if mode == 'exit': sys.exit(1)
    if mode == 'oversized': print('x'*140000); sys.exit(0)
    if mode == 'warning': print(json.dumps({'type':'item.completed','item':{'type':'error','message':'configuration warning'}}))
    messages = {'quota': 'You’ve hit your usage limit. Try again later.', 'disconnect': 'Connection failed: test disconnect', 'request_timeout': 'request timed out'}
    if mode in messages:
        print(json.dumps({'type':'turn.failed','error':{'message':messages[mode]}}))
        sys.exit(1)
if (root/'delay').exists() and (root/'delay').read_text() in ['', role]: time.sleep(10)
result = json.loads((root/(role+'.json')).read_text())
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(result)}}))
print(json.dumps({'type':'turn.completed'}))
"#;
        std::fs::write(&executable, script).unwrap();
        std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o700)).unwrap();
        if delay {
            std::fs::write(dir.0.join("delay"), "").unwrap();
        }
        Self {
            dir,
            ai: SubscriptionAi {
                enabled: true,
                executable,
                timeout: Duration::from_secs(3),
            },
        }
    }
    fn accepted() -> Self {
        Self::new(
            json!(proposal()),
            json!({"verdict":"accept","criteria":[1,2,3,4,5],"evidence":"모든 조건을 확인","reason":"조건을 충족"}),
            false,
        )
    }
    fn calls(&self) -> Vec<Value> {
        std::fs::read_to_string(self.dir.0.join("calls.jsonl"))
            .unwrap_or_default()
            .lines()
            .map(|s| serde_json::from_str(s).unwrap())
            .collect()
    }
}

#[tokio::test]
async fn default_off_never_starts_cli_and_keeps_action() {
    let ai = SubscriptionAi::default();
    assert!(!ai.enabled);
    let old = proposal();
    let mut state = ActionState::new(Some(old.clone()));
    let ticket = state.begin().unwrap();
    let result = ai.evaluate(&input(), ticket).await;
    assert_eq!(result.disposition, Disposition::Disabled);
    assert!(!state.finish(result));
    assert_eq!(state.current(), &Some(old));
}

#[cfg(unix)]
#[tokio::test]
async fn http_disconnect_kills_cli_and_releases_duplicate_request() {
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use tokio::net::{TcpListener, TcpStream};
    use tower::ServiceExt;
    for stage in ["candidate", "check"] {
        let f = Fixture::accepted();
        std::fs::write(f.dir.0.join("delay"), stage).unwrap();
        let expected_calls = if stage == "candidate" { 1 } else { 2 };
        let app = http::router(f.ai.clone(), None);
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(axum::serve(listener, app.clone()).into_future());
        let payload = json!({"state_key":"goal-1:revision-2", "input":input()}).to_string();
        let mut socket = TcpStream::connect(address).await.unwrap();
        socket.write_all(format!("POST /development/suggestions HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}", payload.len(), payload).as_bytes()).await.unwrap();
        for _ in 0..100 {
            if f.calls().len() == expected_calls {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert_eq!(
            f.calls().len(),
            expected_calls,
            "request reaches the selected stage"
        );
        let pid = f.calls().last().unwrap()["pid"]
            .as_u64()
            .unwrap()
            .to_string();
        let response = app
            .clone()
            .oneshot(
                Request::post("/development/suggestions")
                    .header("Content-Type", "application/json")
                    .body(Body::from(payload.clone()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::CONFLICT);
        drop(socket);
        for _ in 0..100 {
            if !std::process::Command::new("kill")
                .args(["-0", &pid])
                .stderr(Stdio::null())
                .status()
                .unwrap()
                .success()
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert!(
            !std::process::Command::new("kill")
                .args(["-0", &pid])
                .stderr(Stdio::null())
                .status()
                .unwrap()
                .success(),
            "disconnect terminates CLI before its 3-second timeout"
        );
        let retry = app
            .oneshot(
                Request::post("/development/suggestions")
                    .header("Content-Type", "application/json")
                    .body(Body::from(payload))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(retry.status(), StatusCode::OK);
        drop(retry);
        assert_eq!(
            f.calls().len(),
            expected_calls,
            "no automatic retry or checker after cancel"
        );
        server.abort();
    }
}

#[cfg(unix)]
#[tokio::test]
async fn accepts_only_after_two_isolated_oauth_calls() {
    let f = Fixture::accepted();
    let mut state = ActionState::new(None);
    let ticket = state.begin().unwrap();
    assert!(matches!(state.begin(), Err(Disposition::Busy)));
    let result = f.ai.evaluate(&input(), ticket).await;
    assert_eq!(result.disposition, Disposition::Accepted);
    assert_eq!(state.current(), &None);
    assert!(state.finish(result));
    assert_eq!(state.current(), &Some(proposal()));
    let calls = f.calls();
    assert_eq!(calls.len(), 2);
    assert_eq!(calls[0]["role"], "candidate");
    assert_eq!(calls[1]["role"], "check");
    assert_eq!(calls[1]["payload"]["original_request"], calls[0]["payload"]);
    assert_eq!(calls[1]["payload"]["candidate"], json!(proposal()));
    for call in calls {
        let args = call["args"].as_array().unwrap();
        for required in [
            MODEL,
            "forced_login_method=\"chatgpt\"",
            "model_reasoning_effort=\"medium\"",
            "features.shell_tool=false",
            "features.unified_exec=false",
            "features.apps=false",
            "features.plugins=false",
            "features.hooks=false",
            "features.view_image=false",
            "web_search=\"disabled\"",
            "--ephemeral",
            "--no-daemon",
            "model_provider=\"smallnext-development\"",
            "model_providers.smallnext-development.requires_openai_auth=true",
            "model_providers.smallnext-development.request_max_retries=0",
            "model_providers.smallnext-development.stream_max_retries=0",
        ] {
            assert!(args.contains(&json!(required)));
        }
        assert_eq!(call["keys"], json!([]));
    }
}

#[cfg(unix)]
#[tokio::test]
async fn http_returns_only_independently_accepted_candidates_without_retries() {
    use axum::{body::Body, http::Request};
    use http_body_util::BodyExt;
    use tower::ServiceExt;
    for verdict in ["accept", "reject", "uncertain"] {
        let f = Fixture::new(
            json!(proposal()),
            json!({"verdict":verdict,"criteria":[1,2,3,4,5],"evidence":"고정 검증 증거","reason":"판정 이유"}),
            false,
        );
        let app = http::router(f.ai.clone(), Some("local-token".into()));
        let response = app
            .oneshot(
                Request::post("/development/suggestions")
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer local-token")
                    .body(Body::from(
                        json!({"state_key":"1:0", "input":input()}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let value: Value = serde_json::from_slice(&body).unwrap();
        if verdict == "accept" {
            assert_eq!(value["disposition"], "accepted");
            assert_eq!(value["proposal"], json!(proposal()));
        } else {
            assert_eq!(
                value["disposition"],
                if verdict == "reject" {
                    "rejected"
                } else {
                    "uncertain"
                }
            );
            assert_eq!(value["proposal"], Value::Null);
        }
        assert_eq!(f.calls().len(), 2);
    }
}

#[cfg(unix)]
#[tokio::test]
async fn cli_transport_failures_keep_their_reason_through_http() {
    use axum::{body::Body, http::Request};
    use http_body_util::BodyExt;
    use tower::ServiceExt;
    for (mode, expected) in [
        ("quota", "budget_limit"),
        ("disconnect", "connection_lost"),
        ("request_timeout", "timed_out"),
    ] {
        let f = Fixture::accepted();
        std::fs::write(f.dir.0.join("mode"), mode).unwrap();
        let response = http::router(f.ai.clone(), None)
            .oneshot(
                Request::post("/development/suggestions")
                    .header("Content-Type", "application/json")
                    .body(Body::from(
                        json!({"state_key":"1:0","input":input()}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        let value: Value =
            serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes())
                .unwrap();
        assert_eq!(value["disposition"], expected);
        assert_eq!(value["proposal"], Value::Null);
        assert_eq!(f.calls().len(), 1);
    }
}

#[cfg(unix)]
#[tokio::test]
async fn checker_accepts_combined_payload_larger_than_original_limit() {
    let mut data = input();
    data.remaining_work = vec!["x".repeat(18 * 1024)];
    let mut candidate = proposal();
    candidate.remaining_work = data.remaining_work.clone();
    assert!(serde_json::to_vec(&data).unwrap().len() < INPUT_LIMIT);
    let f = Fixture::new(
        json!(candidate),
        json!({"verdict":"accept","criteria":[1,2,3,4,5],"evidence":"보존 배열 확인","reason":"모두 충족"}),
        false,
    );
    let mut state = ActionState::new(None);
    let ticket = state.begin().unwrap();
    let result = f.ai.evaluate(&data, ticket).await;
    assert_eq!(result.disposition, Disposition::Accepted);
    assert!(state.finish(result));
    assert_eq!(state.current(), &Some(candidate));
    let calls = f.calls();
    assert_eq!(calls.len(), 2);
    let size = serde_json::to_vec(&calls[1]["payload"]).unwrap().len();
    assert!(size > INPUT_LIMIT && size < CHECK_INPUT_LIMIT);
}

#[cfg(unix)]
#[tokio::test]
async fn checker_reject_uncertain_and_malformed_keep_action_without_retry() {
    for (check, expected) in [
        (
            json!({"verdict":"reject","criteria":[1],"evidence":"불일치","reason":"목표와 다름"}),
            Disposition::Rejected,
        ),
        (
            json!({"verdict":"uncertain","criteria":[2],"evidence":"정보 부족","reason":"판단 불가"}),
            Disposition::Uncertain,
        ),
        (
            json!({"verdict":"accept","criteria":[1,2,3,4],"evidence":"누락","reason":"잘못된 수용"}),
            Disposition::Failed,
        ),
        (
            json!({"verdict":"accept","criteria":[1,2,3,4,5],"evidence":"증거","reason":"수용","extra":true}),
            Disposition::Failed,
        ),
    ] {
        let f = Fixture::new(json!(proposal()), check, false);
        let mut old = proposal();
        old.action = "기존 행동".into();
        let mut state = ActionState::new(Some(old.clone()));
        let ticket = state.begin().unwrap();
        let result = f.ai.evaluate(&input(), ticket).await;
        assert_eq!(result.disposition, expected);
        assert!(!state.finish(result));
        assert_eq!(state.current(), &Some(old));
        assert_eq!(f.calls().len(), 2);
        assert!(state.begin().is_ok());
    }
}

#[cfg(unix)]
#[tokio::test]
async fn invalid_generation_never_starts_checker() {
    for field in [
        "goal_completed",
        "remaining_work",
        "estimated_minutes",
        "status",
    ] {
        let mut candidate = json!(proposal());
        candidate[field] = match field {
            "goal_completed" => json!(true),
            "remaining_work" => json!([]),
            "estimated_minutes" => json!(3),
            _ => json!("unsupported"),
        };
        let f = Fixture::new(candidate, json!({}), false);
        let mut state = ActionState::new(None);
        let ticket = state.begin().unwrap();
        let result = f.ai.evaluate(&input(), ticket).await;
        assert_eq!(result.disposition, Disposition::InvalidProposal);
        assert!(!state.finish(result));
        assert_eq!(f.calls().len(), 1);
    }
}

#[cfg(unix)]
#[tokio::test]
async fn wrong_context_status_never_starts_checker_or_changes_current_action() {
    for (kind, status) in [
        ("goal_preparation", ProposalStatus::Action),
        ("goal_preparation", ProposalStatus::Minimum),
        ("smaller", ProposalStatus::NoAction),
        ("smaller", ProposalStatus::GoalSummary),
        ("next_action", ProposalStatus::NoAction),
        ("first_action", ProposalStatus::NoAction),
        ("replacement", ProposalStatus::GoalSummary),
    ] {
        let mut data = input();
        data.request_kind = Some(kind.into());
        let mut candidate = proposal();
        candidate.status = status;
        let f = Fixture::new(json!(candidate), json!({}), false);
        let old = proposal();
        let mut state = ActionState::new(Some(old.clone()));
        let ticket = state.begin().unwrap();
        let result = f.ai.evaluate(&data, ticket).await;
        assert_eq!(result.disposition, Disposition::InvalidProposal);
        assert!(!state.finish(result));
        assert_eq!(state.current(), &Some(old));
        let calls = f.calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0]["schema"], generation_schema(Some(kind)));
        assert_eq!(calls[0]["system"], include_str!("generate.md"));
    }
}

#[cfg(unix)]
#[tokio::test]
async fn invalid_input_never_starts_cli() {
    let f = Fixture::accepted();
    for large in [false, true] {
        let mut data = input();
        data.goal = if large {
            "x".repeat(INPUT_LIMIT)
        } else {
            " ".into()
        };
        let mut state = ActionState::new(None);
        let ticket = state.begin().unwrap();
        let result = f.ai.evaluate(&data, ticket).await;
        assert_eq!(result.disposition, Disposition::InvalidInput);
        assert!(!state.finish(result));
    }
    assert!(f.calls().is_empty());
}

#[cfg(unix)]
#[tokio::test]
async fn cli_failures_keep_action_and_remove_scratch_files() {
    for mode in ["exit", "oversized", "warning"] {
        let f = Fixture::accepted();
        std::fs::write(f.dir.0.join("mode"), mode).unwrap();
        let mut state = ActionState::new(Some(proposal()));
        let ticket = state.begin().unwrap();
        let result = f.ai.evaluate(&input(), ticket).await;
        assert_eq!(result.disposition, Disposition::Failed);
        assert!(!state.finish(result));
        assert_eq!(state.current(), &Some(proposal()));
        let calls = f.calls();
        assert_eq!(calls.len(), 1);
        let args = calls[0]["args"].as_array().unwrap();
        let schema = args[args.iter().position(|v| v == "--output-schema").unwrap() + 1]
            .as_str()
            .unwrap();
        assert!(!std::path::Path::new(schema).exists());
    }
}

#[cfg(unix)]
#[tokio::test]
async fn cancellation_timeout_and_stale_response_preserve_state() {
    let mut f = Fixture::new(json!(proposal()), json!({}), true);
    let old = proposal();
    let mut state = ActionState::new(Some(old.clone()));
    let ticket = state.begin().unwrap();
    let data = input();
    let run = f.ai.evaluate(&data, ticket);
    let cancel = async {
        for _ in 0..100 {
            if !f.calls().is_empty() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        state.cancel();
    };
    let (result, _) = tokio::join!(run, cancel);
    assert_eq!(result.disposition, Disposition::Superseded);
    assert!(!state.finish(result));
    assert_eq!(state.current(), &Some(old.clone()));
    assert_eq!(f.calls().len(), 1);
    let pid = f.calls()[0]["pid"].as_u64().unwrap().to_string();
    for _ in 0..50 {
        let alive = std::process::Command::new("kill")
            .args(["-0", &pid])
            .stderr(Stdio::null())
            .status()
            .unwrap()
            .success();
        if !alive {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(
        !std::process::Command::new("kill")
            .args(["-0", &pid])
            .stderr(Stdio::null())
            .status()
            .unwrap()
            .success()
    );
    f.ai.timeout = Duration::from_millis(50);
    let ticket = state.begin().unwrap();
    let result = f.ai.evaluate(&data, ticket).await;
    assert_eq!(result.disposition, Disposition::TimedOut);
    assert!(!state.finish(result));
    assert_eq!(state.current(), &Some(old));
    let f = Fixture::accepted();
    let mut state = ActionState::new(None);
    let ticket = state.begin().unwrap();
    let result = f.ai.evaluate(&data, ticket).await;
    state.cancel();
    assert!(!state.finish(result));
    assert!(state.current().is_none());
    let ticket = state.begin().unwrap();
    let result = f.ai.evaluate(&data, ticket).await;
    let mut other = ActionState::new(None);
    other.begin().unwrap();
    other.cancel();
    other.begin().unwrap();
    assert_eq!(other.revision, state.revision);
    assert!(!other.finish(result));
    assert!(other.current().is_none());
}

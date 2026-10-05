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
        let dir = Workspace::new("generate").unwrap();
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
    log.write(json.dumps({'role':role,'payload':payload,'args':args,'pid':os.getpid(),'keys':[k for k in ['OPENAI_API_KEY','CODEX_API_KEY','OPENAI_BASE_URL','GH_TOKEN','GITHUB_TOKEN','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN'] if k in os.environ]})+'\n')
if (root/'mode').exists():
    mode = (root/'mode').read_text()
    if mode == 'exit': sys.exit(1)
    if mode == 'oversized': print('x'*140000); sys.exit(0)
    if mode == 'warning': print(json.dumps({'type':'item.completed','item':{'type':'error','message':'configuration warning'}}))
if (root/'delay').exists(): time.sleep(10)
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
        ] {
            assert!(args.contains(&json!(required)));
        }
        assert_eq!(call["keys"], json!([]));
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

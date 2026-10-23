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

/// Model output: the app proposal plus the model-only grounding fields.
fn generated() -> Value {
    let mut value = json!(proposal());
    value["facts"] =
        json!([{"fact":"파란 펜이 책상 왼쪽에 있다","source":"present","if_absent":"해당 없음"}]);
    value["reduction"] = json!("해당 없음");
    value
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
            let schema = schema(Role::Generate, kind);
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

/// In-memory adapter: replies in order and records each role it was asked for.
struct Scripted {
    replies: std::sync::Mutex<Vec<Result<Value, Disposition>>>,
    calls: std::sync::Mutex<Vec<(Role, Value)>>,
}
impl Scripted {
    fn new(replies: Vec<Result<Value, Disposition>>) -> Self {
        Self {
            replies: std::sync::Mutex::new(replies.into_iter().rev().collect()),
            calls: std::sync::Mutex::default(),
        }
    }
    fn roles(&self) -> Vec<Role> {
        self.calls.lock().unwrap().iter().map(|c| c.0).collect()
    }
}
impl Model for Scripted {
    type Bill = Role;
    async fn call(&self, role: Role, payload: &Value) -> (Result<Value, Disposition>, Role) {
        self.calls.lock().unwrap().push((role, payload.clone()));
        (
            self.replies.lock().unwrap().pop().expect("scripted reply"),
            role,
        )
    }
}

fn accept() -> Value {
    json!({"verdict":"accept","criteria":[1,2,3,4,5],"evidence":"원본 인용","reason":"조건 충족"})
}

#[tokio::test]
async fn accepted_candidate_is_checked_against_the_original_request() {
    let model = Scripted::new(vec![Ok(generated()), Ok(accept())]);
    let evaluation = evaluate(&model, &input()).await;
    assert_eq!(
        evaluation.result,
        Ok(proposal()),
        "grounding never reaches the app"
    );
    assert_eq!(evaluation.bills, [Role::Generate, Role::Check]);
    let calls = model.calls.lock().unwrap();
    assert_eq!(calls[0].1, validate_input(&input()).unwrap());
    assert_eq!(calls[1].1["original_request"], calls[0].1);
    assert_eq!(
        calls[1].1["candidate"],
        generated(),
        "the checker compares grounding"
    );
}

#[tokio::test]
async fn invalid_or_failed_generation_never_starts_the_checker() {
    let mut completed = generated();
    completed["goal_completed"] = json!(true);
    let mut unsourced = generated();
    unsourced["facts"][0]["source"] = json!("memory");
    let mut extra = generated();
    extra["facts"][0]["note"] = json!("추가");
    for (reply, expected) in [
        (Err(Disposition::BudgetLimit), Disposition::BudgetLimit),
        (Ok(json!({"status":"action"})), Disposition::InvalidProposal),
        (Ok(completed), Disposition::InvalidProposal),
        (Ok(json!(proposal())), Disposition::InvalidProposal),
        (Ok(unsourced), Disposition::InvalidProposal),
        (Ok(extra), Disposition::InvalidProposal),
    ] {
        let model = Scripted::new(vec![reply]);
        let evaluation = evaluate(&model, &input()).await;
        assert_eq!(evaluation.result, Err(expected));
        assert_eq!(model.roles(), [Role::Generate], "{expected:?}");
        assert_eq!(
            evaluation.bills,
            [Role::Generate],
            "a started call keeps its bill"
        );
    }
}

#[tokio::test]
async fn checker_verdict_or_failure_decides_without_retry() {
    let mut reject = accept();
    reject["verdict"] = json!("reject");
    reject["criteria"] = json!([2]);
    for (reply, expected) in [
        (Ok(reject), Disposition::Rejected),
        (Ok(json!({"verdict":"accept"})), Disposition::Failed),
        (
            Err(Disposition::ConnectionLost),
            Disposition::ConnectionLost,
        ),
    ] {
        let model = Scripted::new(vec![Ok(generated()), reply]);
        let evaluation = evaluate(&model, &input()).await;
        assert_eq!(evaluation.result, Err(expected));
        assert_eq!(evaluation.bills, [Role::Generate, Role::Check]);
    }
}

#[tokio::test]
async fn invalid_input_starts_no_model_call() {
    let mut data = input();
    data.goal = " ".into();
    let model = Scripted::new(vec![]);
    let evaluation = evaluate(&model, &data).await;
    assert_eq!(evaluation.result, Err(Disposition::InvalidInput));
    assert!(evaluation.bills.is_empty());
}

/// scripts/oauth_quality.py replays this contract; both suites compare against one fixture.
#[test]
fn compact_contract_matches_shared_fixture() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../contracts/fixtures/suggestion-compact.json"
    );
    let committed: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let mut actual = json!({
        "cases": committed["cases"],
        "prompts": {},
        "schemas": {},
        "statuses": {},
    });
    for case in committed["cases"].as_array().unwrap() {
        let role = match case["role"].as_str().unwrap() {
            "generate" => Role::Generate,
            _ => Role::Check,
        };
        let (prompt, schema) = compact::request(role, &case["payload"]);
        let (p, s) = (
            case["prompt"].as_str().unwrap(),
            case["schema"].as_str().unwrap(),
        );
        assert!(
            actual["prompts"].get(p).is_none_or(|old| old == &prompt),
            "{p}"
        );
        assert!(
            actual["schemas"].get(s).is_none_or(|old| old == &schema),
            "{s}"
        );
        actual["prompts"][p] = json!(prompt);
        actual["schemas"][s] = schema;
    }
    for kind in [
        "goal_preparation",
        "first_action",
        "next_action",
        "smaller",
        "replacement",
    ] {
        actual["statuses"][kind] = json!(allowed_statuses(Some(kind)));
    }
    actual["statuses"]["none"] = json!(allowed_statuses(None));
    // A contract.md edit that breaks the paragraph shape silently drops the question projection.
    assert!(
        actual["prompts"]["check-question"]
            .as_str()
            .unwrap()
            .starts_with("Independently check all five mandatory criteria")
    );
    if std::env::var_os("UPDATE_CONTRACT_FIXTURES").is_some() {
        std::fs::write(path, serde_json::to_string_pretty(&actual).unwrap() + "\n").unwrap();
        return;
    }
    assert_eq!(
        actual, committed,
        "run UPDATE_CONTRACT_FIXTURES=1 cargo test, then update scripts/oauth_quality.py"
    );
}

#[tokio::test]
async fn insufficient_info_is_checked_without_creating_an_action() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../../contracts/fixtures/insufficient-info.json"
    ))
    .unwrap();
    for kind in ["first_action", "next_action", "smaller", "replacement"] {
        let mut original = fixture["input"].clone();
        original["request_kind"] = json!(kind);
        let data: AiInput = serde_json::from_value(original).unwrap();
        let model = Scripted::new(vec![Ok(fixture["generated"].clone()), Ok(accept())]);
        let evaluated = evaluate(&model, &data).await;
        assert_eq!(
            evaluated.result.unwrap(),
            serde_json::from_value(fixture["response"]["proposal"].clone()).unwrap()
        );
        assert_eq!(model.roles(), [Role::Generate, Role::Check]);
    }
    for case in fixture["checker_cases"].as_array().unwrap() {
        let data = serde_json::from_value(case["input"].clone()).unwrap();
        let model = Scripted::new(vec![
            Ok(fixture["generated"].clone()),
            Ok(case["check"].clone()),
        ]);
        let evaluated = evaluate(&model, &data).await;
        let disposition = match evaluated.result {
            Ok(_) => Disposition::Accepted,
            Err(failure) => failure,
        };
        assert_eq!(json!(disposition), case["expected"], "{}", case["id"]);
        assert_eq!(model.roles(), [Role::Generate, Role::Check]);
    }
}

#[tokio::test]
async fn invalid_insufficient_info_never_starts_checker() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../../contracts/fixtures/insufficient-info.json"
    ))
    .unwrap();
    let original: AiInput = serde_json::from_value(fixture["input"].clone()).unwrap();
    for (field, value) in [
        ("action", json!("가짜 행동")),
        ("completion_condition", json!(" ")),
        ("estimated_minutes", json!(1)),
        ("estimated_minutes", json!(-1)),
        ("reason", json!(" ")),
        ("reduction", json!("해당 없음")),
        ("remaining_work", json!([])),
        ("preserved_completed_ids", json!(["new"])),
        ("goal_completed", json!(true)),
        ("current_action_completed", json!(true)),
    ] {
        let mut generated = fixture["generated"].clone();
        generated[field] = value;
        let model = Scripted::new(vec![Ok(generated)]);
        assert_eq!(
            evaluate(&model, &original).await.result,
            Err(Disposition::InvalidProposal),
            "{field}"
        );
        assert_eq!(model.roles(), [Role::Generate]);
    }
    for kind in [None, Some("goal_preparation"), Some("unsupported")] {
        let mut data = fixture["input"].clone();
        data["request_kind"] = json!(kind);
        let data = serde_json::from_value(data).unwrap();
        let model = Scripted::new(vec![Ok(fixture["generated"].clone())]);
        let expected = if kind == Some("unsupported") {
            Disposition::InvalidInput
        } else {
            Disposition::InvalidProposal
        };
        assert_eq!(evaluate(&model, &data).await.result, Err(expected));
        assert_eq!(
            model.roles().len(),
            usize::from(kind != Some("unsupported"))
        );
    }
    let mut data = original;
    data.remaining_work = vec!["둘째".into(), "첫째".into()];
    data.completed_ids = vec!["2".into(), "1".into()];
    let mut generated = fixture["generated"].clone();
    generated["remaining_work"] = json!(data.remaining_work);
    generated["preserved_completed_ids"] = json!(data.completed_ids);
    let model = Scripted::new(vec![Ok(generated), Ok(accept())]);
    let proposal = evaluate(&model, &data).await.result.unwrap();
    assert_eq!(proposal.remaining_work, data.remaining_work);
    assert_eq!(proposal.preserved_completed_ids, data.completed_ids);
}

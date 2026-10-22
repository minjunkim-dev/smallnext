//! Product contract for one action suggestion, shared by every model adapter.
pub(crate) mod compact;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use utoipa::ToSchema;

pub(crate) const INPUT_LIMIT: usize = 32 * 1024;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum ProposalStatus {
    Action,
    NeedInfo,
    Minimum,
    GoalSummary,
    NoAction,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct Proposal {
    pub status: ProposalStatus,
    pub action: String,
    pub completion_condition: String,
    pub estimated_minutes: f64,
    pub reason: String,
    pub remaining_work: Vec<String>,
    pub goal_completed: bool,
    pub current_action_completed: bool,
    pub preserved_completed_ids: Vec<String>,
}

/// Model-only fields the checker compares; the app response never carries them (#259).
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Grounding {
    facts: Vec<Fact>,
    reduction: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Fact {
    fact: String,
    source: FactSource,
    if_absent: String,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum FactSource {
    Present,
    Absent,
    Unknown,
}

#[derive(Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct AiInput {
    pub goal: String,
    pub current_blocker: String,
    pub user_request: String,
    pub available: Vec<String>,
    pub unknown: Vec<String>,
    pub available_minutes: f64,
    pub knowledge: String,
    pub energy: String,
    pub remaining_work: Vec<String>,
    pub completed_ids: Vec<String>,
    pub previous_proposals: Vec<Proposal>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_kind: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Check {
    verdict: Verdict,
    criteria: Vec<u8>,
    evidence: String,
    reason: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Verdict {
    Accept,
    Reject,
    Uncertain,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Disposition {
    Accepted,
    Disabled,
    Busy,
    InvalidInput,
    InvalidProposal,
    Rejected,
    Uncertain,
    Failed,
    TimedOut,
    Superseded,
    BudgetLimit,
    ConnectionLost,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Role {
    Generate,
    Check,
}
impl Role {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Role::Generate => "generate",
            Role::Check => "check",
        }
    }
}

/// One model call. An adapter returns the full-shape JSON for its role and its own bill.
pub(crate) trait Model {
    type Bill;
    async fn call(&self, role: Role, payload: &Value) -> (Result<Value, Disposition>, Self::Bill);
}

pub(crate) struct Evaluation<B> {
    pub result: Result<Proposal, Disposition>,
    /// One bill per started call, in call order.
    pub bills: Vec<B>,
}

/// Generate, validate, then check independently. An invalid candidate never starts the checker.
pub(crate) async fn evaluate<M: Model>(model: &M, input: &AiInput) -> Evaluation<M::Bill> {
    let mut bills = Vec::new();
    let result = async {
        let original = validate_input(input)?;
        let (generated, bill) =
            crate::timing::measure(Role::Generate, model.call(Role::Generate, &original)).await;
        bills.push(bill);
        let (proposal, grounding) = split(generated?)?;
        validate_proposal(input, &proposal)?;
        let mut candidate = json!(proposal);
        candidate["facts"] = json!(grounding.facts);
        candidate["reduction"] = json!(grounding.reduction);
        let payload = json!({"original_request": original, "candidate": candidate});
        let (checked, bill) =
            crate::timing::measure(Role::Check, model.call(Role::Check, &payload)).await;
        bills.push(bill);
        validate_check(checked?)?;
        Ok(proposal)
    }
    .await;
    Evaluation { result, bills }
}

pub(crate) fn validate_input(input: &AiInput) -> Result<Value, Disposition> {
    let original = serde_json::to_value(input).map_err(|_| Disposition::InvalidInput)?;
    let size = serde_json::to_vec(&original)
        .map_err(|_| Disposition::InvalidInput)?
        .len();
    if size > INPUT_LIMIT
        || input.goal.trim().is_empty()
        || input.user_request.trim().is_empty()
        || !input.available_minutes.is_finite()
        || input.available_minutes < 0.0
        || input.current_blocker.len() > 2048
        || input.request_kind.as_deref().is_some_and(|kind| {
            !matches!(
                kind,
                "goal_preparation" | "first_action" | "next_action" | "smaller" | "replacement"
            )
        })
    {
        return Err(Disposition::InvalidInput);
    }
    Ok(original)
}

fn allowed_statuses(kind: Option<&str>) -> &'static [ProposalStatus] {
    use ProposalStatus::*;
    match kind {
        Some("goal_preparation") => &[GoalSummary, NeedInfo],
        Some("replacement") => &[Action, NeedInfo, Minimum, NoAction],
        _ => &[Action, NeedInfo, Minimum],
    }
}

/// Full output schema for a role; generation narrows the status to the request kind.
pub(crate) fn schema(role: Role, kind: Option<&str>) -> Value {
    match role {
        Role::Generate => {
            let mut schema: Value = serde_json::from_str(include_str!("suggestion/generate.json"))
                .expect("committed schema");
            schema["properties"]["status"]["enum"] = json!(allowed_statuses(kind));
            schema
        }
        Role::Check => {
            serde_json::from_str(include_str!("suggestion/check.json")).expect("committed schema")
        }
    }
}

/// Schema text for adapters that hand the file to a model. The check schema keeps its
/// committed key order; structured output follows that order.
pub(crate) fn schema_text(role: Role, kind: Option<&str>) -> String {
    match role {
        Role::Generate => schema(role, kind).to_string(),
        Role::Check => include_str!("suggestion/check.json").to_owned(),
    }
}

/// Role instructions followed by the one contract shared by generation and checking.
pub(crate) fn instructions(role: Role) -> String {
    let instructions = match role {
        Role::Generate => include_str!("suggestion/generate.md"),
        Role::Check => include_str!("suggestion/check.md"),
    };
    format!("{instructions}\n{}", include_str!("suggestion/contract.md"))
}

fn split(mut generated: Value) -> Result<(Proposal, Grounding), Disposition> {
    let object = generated
        .as_object_mut()
        .ok_or(Disposition::InvalidProposal)?;
    let grounding =
        json!({"facts": object.remove("facts"), "reduction": object.remove("reduction")});
    Ok((
        serde_json::from_value(generated).map_err(|_| Disposition::InvalidProposal)?,
        serde_json::from_value(grounding).map_err(|_| Disposition::InvalidProposal)?,
    ))
}

fn validate_proposal(input: &AiInput, proposal: &Proposal) -> Result<(), Disposition> {
    if proposal.action.trim().is_empty()
        || proposal.completion_condition.trim().is_empty()
        || proposal.reason.trim().is_empty()
        || !proposal.estimated_minutes.is_finite()
        || proposal.estimated_minutes < 0.0
        || proposal.estimated_minutes > input.available_minutes
        || proposal.goal_completed
        || proposal.current_action_completed
        || proposal.remaining_work != input.remaining_work
        || proposal.preserved_completed_ids != input.completed_ids
        || !allowed_statuses(input.request_kind.as_deref()).contains(&proposal.status)
    {
        return Err(Disposition::InvalidProposal);
    }
    Ok(())
}

fn validate_check(value: Value) -> Result<(), Disposition> {
    let check: Check = serde_json::from_value(value).map_err(|_| Disposition::Failed)?;
    if check.evidence.trim().is_empty()
        || check.reason.trim().is_empty()
        || check.criteria.is_empty()
        || check.criteria.iter().any(|c| !(1..=5).contains(c))
    {
        return Err(Disposition::Failed);
    }
    match check.verdict {
        Verdict::Accept if (1..=5).all(|c| check.criteria.contains(&c)) => Ok(()),
        Verdict::Accept => Err(Disposition::Failed),
        Verdict::Reject => Err(Disposition::Rejected),
        Verdict::Uncertain => Err(Disposition::Uncertain),
    }
}

#[cfg(test)]
mod tests;

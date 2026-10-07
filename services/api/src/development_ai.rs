//! Developer's Mac only. HTTP access requires the local development flag.
pub mod http;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    path::PathBuf,
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    process::Command,
    sync::watch,
};

pub const MODEL: &str = "gpt-6.1-sol";
const INPUT_LIMIT: usize = 32 * 1024;
const OUTPUT_LIMIT: u64 = 128 * 1024;
// The checker receives both the original input and the bounded generator result.
const CHECK_INPUT_LIMIT: usize = 192 * 1024;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum ProposalStatus {
    Action,
    NeedInfo,
    Minimum,
    GoalSummary,
    NoAction,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
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

#[derive(Serialize, Deserialize)]
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

/// Only the evaluator can construct a candidate that has passed both stages.
pub struct Outcome {
    identity: Arc<()>,
    revision: u64,
    pub disposition: Disposition,
    proposal: Option<Proposal>,
}
pub struct Ticket {
    identity: Arc<()>,
    revision: u64,
    changes: watch::Receiver<u64>,
}

/// Call cancel when the goal/input changes, or the user cancels the active request.
pub struct ActionState {
    identity: Arc<()>,
    revision: u64,
    pending: bool,
    changes: watch::Sender<u64>,
    current: Option<Proposal>,
}
impl ActionState {
    pub fn new(current: Option<Proposal>) -> Self {
        let (changes, _) = watch::channel(0);
        Self {
            identity: Arc::new(()),
            revision: 0,
            pending: false,
            changes,
            current,
        }
    }
    pub fn current(&self) -> &Option<Proposal> {
        &self.current
    }
    pub fn begin(&mut self) -> Result<Ticket, Disposition> {
        if self.pending {
            return Err(Disposition::Busy);
        }
        self.advance();
        self.pending = true;
        Ok(Ticket {
            identity: self.identity.clone(),
            revision: self.revision,
            changes: self.changes.subscribe(),
        })
    }
    fn advance(&mut self) {
        self.revision = self
            .revision
            .checked_add(1)
            .expect("request revision exhausted");
        self.changes.send_replace(self.revision);
    }
    pub fn cancel(&mut self) {
        self.advance();
        self.pending = false;
    }
    pub fn finish(&mut self, outcome: Outcome) -> bool {
        if !self.pending
            || outcome.revision != self.revision
            || !Arc::ptr_eq(&self.identity, &outcome.identity)
        {
            return false;
        }
        self.pending = false;
        if let Some(proposal) = outcome.proposal {
            self.current = Some(proposal);
            true
        } else {
            false
        }
    }
}

#[derive(Clone)]
pub struct SubscriptionAi {
    enabled: bool,
    executable: PathBuf,
    timeout: Duration,
}
impl Default for SubscriptionAi {
    fn default() -> Self {
        let registry: Value =
            serde_json::from_str(include_str!("../../../config/feature-flags.json"))
                .unwrap_or(Value::Null);
        let enabled = registry["flags"].as_array().is_some_and(|flags| {
            let matching: Vec<_> = flags
                .iter()
                .filter(|f| f["key"] == "development_subscription_ai")
                .collect();
            matching.len() == 1 && matching[0]["default"] == true
        });
        Self {
            enabled,
            executable: "codex".into(),
            timeout: Duration::from_secs(120),
        }
    }
}
impl SubscriptionAi {
    /// Explicit override for the developer's local CLI or development HTTP server.
    pub fn for_local_development() -> Self {
        Self {
            enabled: true,
            ..Self::default()
        }
    }
    pub async fn evaluate(&self, input: &AiInput, mut ticket: Ticket) -> Outcome {
        let result = if !self.enabled {
            Err(Disposition::Disabled)
        } else if *ticket.changes.borrow() != ticket.revision {
            Err(Disposition::Superseded)
        } else {
            tokio::select! {
                biased;
                _ = ticket.changes.changed() => Err(Disposition::Superseded),
                result = tokio::time::timeout(self.timeout, self.pipeline(input)) => result.unwrap_or(Err(Disposition::TimedOut)),
            }
        };
        // The application checks the revision again immediately before replacing its action.
        match result {
            Ok(proposal) => Outcome {
                identity: ticket.identity,
                revision: ticket.revision,
                disposition: Disposition::Accepted,
                proposal: Some(proposal),
            },
            Err(disposition) => Outcome {
                identity: ticket.identity,
                revision: ticket.revision,
                disposition,
                proposal: None,
            },
        }
    }
    async fn pipeline(&self, input: &AiInput) -> Result<Proposal, Disposition> {
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
        let proposal: Proposal = serde_json::from_value(self.call("generate", &original).await?)
            .map_err(|_| Disposition::InvalidProposal)?;
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
            || (proposal.status == ProposalStatus::GoalSummary
                && input.request_kind.as_deref() != Some("goal_preparation"))
            || (proposal.status == ProposalStatus::NoAction
                && input.request_kind.as_deref() != Some("replacement"))
        {
            return Err(Disposition::InvalidProposal);
        }
        let check: Check = serde_json::from_value(
            self.call(
                "check",
                &json!({"original_request": original, "candidate": proposal}),
            )
            .await?,
        )
        .map_err(|_| Disposition::Failed)?;
        if check.evidence.trim().is_empty()
            || check.reason.trim().is_empty()
            || check.criteria.is_empty()
            || check.criteria.iter().any(|c| !(1..=5).contains(c))
        {
            return Err(Disposition::Failed);
        }
        match check.verdict {
            Verdict::Accept if (1..=5).all(|c| check.criteria.contains(&c)) => Ok(proposal),
            Verdict::Accept => Err(Disposition::Failed),
            Verdict::Reject => Err(Disposition::Rejected),
            Verdict::Uncertain => Err(Disposition::Uncertain),
        }
    }
    async fn call(&self, role: &str, payload: &Value) -> Result<Value, Disposition> {
        let input = serde_json::to_vec(payload).map_err(|_| Disposition::InvalidInput)?;
        let input_limit = if role == "check" {
            CHECK_INPUT_LIMIT
        } else {
            INPUT_LIMIT
        };
        if input.len() > input_limit {
            return Err(Disposition::InvalidInput);
        }
        let workspace = Workspace::new(role)?;
        let mut command = Command::new(&self.executable);
        command
            .args([
                "--no-daemon",
                "exec",
                "--ignore-user-config",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
            ])
            .args([
                "-c",
                "forced_login_method=\"chatgpt\"",
                "-c",
                "approval_policy=\"never\"",
                "-c",
                "features.shell_tool=false",
                "-c",
                "features.unified_exec=false",
                "-c",
                "features.apps=false",
                "-c",
                "features.plugins=false",
                "-c",
                "features.hooks=false",
                "-c",
                "features.browser_use=false",
                "-c",
                "features.computer_use=false",
                "-c",
                "features.image_generation=false",
                "-c",
                "features.code_mode=false",
                "-c",
                "web_search=\"disabled\"",
                "-c",
                "features.view_image=false",
                "-c",
                "skills.max_context_tokens=1",
                "-c",
                "model_reasoning_effort=\"medium\"",
                "-c",
                "model_provider=\"smallnext-development\"",
                "-c",
                "model_providers.smallnext-development.name=\"OpenAI\"",
                "-c",
                "model_providers.smallnext-development.requires_openai_auth=true",
                "-c",
                "model_providers.smallnext-development.request_max_retries=0",
                "-c",
                "model_providers.smallnext-development.stream_max_retries=0",
            ])
            .arg("-c")
            .arg(format!(
                "model_instructions_file={}",
                serde_json::to_string(&workspace.0.join("system.md"))
                    .map_err(|_| Disposition::Failed)?
            ))
            .args(["--model", MODEL, "--output-schema"])
            .arg(workspace.0.join("schema.json"))
            .args(["--json", "-"])
            .current_dir(&workspace.0)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        command.env_clear();
        // Keep only CLI discovery, its own login location, and network configuration.
        for key in [
            "PATH",
            "HOME",
            "CODEX_HOME",
            "TMPDIR",
            "SYSTEMROOT",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
        ] {
            if let Some(value) = std::env::var_os(key) {
                command.env(key, value);
            }
        }
        let mut child = command.spawn().map_err(|_| Disposition::Failed)?;
        let mut stdin = child.stdin.take().ok_or(Disposition::Failed)?;
        stdin
            .write_all(&input)
            .await
            .map_err(|_| Disposition::Failed)?;
        drop(stdin);
        let mut output = Vec::new();
        child
            .stdout
            .take()
            .ok_or(Disposition::Failed)?
            .take(OUTPUT_LIMIT + 1)
            .read_to_end(&mut output)
            .await
            .map_err(|_| Disposition::Failed)?;
        if output.len() as u64 > OUTPUT_LIMIT {
            return Err(Disposition::Failed);
        }
        let parsed = parse_events(&output);
        if !child
            .wait()
            .await
            .map_err(|_| Disposition::Failed)?
            .success()
        {
            return Err(parsed.err().unwrap_or(Disposition::Failed));
        }
        parsed
    }
}

fn parse_events(bytes: &[u8]) -> Result<Value, Disposition> {
    let text = std::str::from_utf8(bytes).map_err(|_| Disposition::Failed)?;
    let mut result = None;
    let mut completed = false;
    for line in text.lines().filter(|s| !s.trim().is_empty()) {
        let event: Value = serde_json::from_str(line).map_err(|_| Disposition::Failed)?;
        match event["type"].as_str() {
            Some("turn.failed") => return Err(cli_failure(&event["error"])),
            Some("error") => return Err(cli_failure(&event)),
            Some("turn.completed") => {
                if completed {
                    return Err(Disposition::Failed);
                }
                completed = true;
            }
            Some("item.started" | "item.updated" | "item.completed") => {
                match event["item"]["type"].as_str() {
                    Some("agent_message") if event["type"] == "item.completed" => {
                        if result.is_some() {
                            return Err(Disposition::Failed);
                        }
                        result = Some(
                            serde_json::from_str(
                                event["item"]["text"].as_str().ok_or(Disposition::Failed)?,
                            )
                            .map_err(|_| Disposition::Failed)?,
                        );
                    }
                    Some("agent_message" | "reasoning") => (),
                    // Codex reports this intentional catalog removal as an error item.
                    // Accept only the exact no-skills notice; configuration/tool errors fail.
                    Some("error") if empty_skills_notice(&event["item"]) => (),
                    Some("error") => return Err(cli_failure(&event["item"])),
                    _ => return Err(Disposition::Failed),
                }
            }
            Some("thread.started" | "turn.started") => (),
            _ => return Err(Disposition::Failed),
        }
    }
    if !completed {
        return Err(Disposition::Failed);
    }
    result.ok_or(Disposition::Failed)
}

// Codex exec exposes only an error message, not a structured error code.
// Match known upstream prefixes; unknown or changed messages still fail closed.
fn cli_failure(error: &Value) -> Disposition {
    let message = error["message"].as_str().unwrap_or("");
    if message.starts_with("You've hit your usage limit")
        || message.starts_with("You’ve hit your usage limit")
        || message.starts_with("You hit your spend cap")
        || message.starts_with("Quota exceeded.")
    {
        Disposition::BudgetLimit
    } else if message.starts_with("Connection failed:")
        || message.starts_with("stream disconnected before completion:")
    {
        if message.contains("reason: content_filter") {
            Disposition::Rejected
        } else {
            Disposition::ConnectionLost
        }
    } else if message == "request timed out" {
        Disposition::TimedOut
    } else {
        Disposition::Failed
    }
}

fn empty_skills_notice(item: &Value) -> bool {
    item["message"]
        .as_str()
        .and_then(|message| {
            message
                .strip_prefix(
                    "Exceeded skills context budget. All skill descriptions were removed and ",
                )?
                .strip_suffix(
                    " additional skills were not included in the model-visible skills list.",
                )?
                .parse::<u32>()
                .ok()
        })
        .is_some()
}

struct Workspace(PathBuf);
impl Workspace {
    fn new(role: &str) -> Result<Self, Disposition> {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "smallnext-subscription-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(&path).map_err(|_| Disposition::Failed)?;
        let workspace = Self(path);
        let (system, schema) = match role {
            "generate" => (
                include_str!("development_ai/generate.md"),
                include_str!("development_ai/generate.json"),
            ),
            "check" => (
                include_str!("development_ai/check.md"),
                include_str!("development_ai/check.json"),
            ),
            _ => return Err(Disposition::Failed),
        };
        std::fs::write(workspace.0.join("system.md"), system).map_err(|_| Disposition::Failed)?;
        std::fs::write(workspace.0.join("schema.json"), schema).map_err(|_| Disposition::Failed)?;
        Ok(workspace)
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[cfg(test)]
mod tests;

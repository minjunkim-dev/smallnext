//! Developer's Mac only: the Codex CLI adapter. HTTP access requires the local development flag.
pub mod http;
use crate::suggestion::{self, AiInput, Disposition, INPUT_LIMIT, Model, Proposal, Role};
use serde_json::Value;
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
const OUTPUT_LIMIT: u64 = 128 * 1024;
// The checker receives both the original input and the bounded generator result.
const CHECK_INPUT_LIMIT: usize = 192 * 1024;

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
        let enabled = crate::transport::flag_default("development_subscription_ai");
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
                evaluation = tokio::time::timeout(self.timeout, suggestion::evaluate(self, input)) => evaluation.map_or(Err(Disposition::TimedOut), |e| e.result),
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
    async fn exec(&self, role: Role, payload: &Value) -> Result<Value, Disposition> {
        let input = serde_json::to_vec(payload).map_err(|_| Disposition::InvalidInput)?;
        let input_limit = if role == Role::Check {
            CHECK_INPUT_LIMIT
        } else {
            INPUT_LIMIT
        };
        if input.len() > input_limit {
            return Err(Disposition::InvalidInput);
        }
        let workspace = Workspace::new(role, payload["request_kind"].as_str())?;
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
impl Model for SubscriptionAi {
    type Bill = ();
    async fn call(&self, role: Role, payload: &Value) -> (Result<Value, Disposition>, ()) {
        (self.exec(role, payload).await, ())
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
    fn new(role: Role, kind: Option<&str>) -> Result<Self, Disposition> {
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
        std::fs::write(
            workspace.0.join("system.md"),
            suggestion::instructions(role),
        )
        .map_err(|_| Disposition::Failed)?;
        std::fs::write(
            workspace.0.join("schema.json"),
            suggestion::schema_text(role, kind),
        )
        .map_err(|_| Disposition::Failed)?;
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

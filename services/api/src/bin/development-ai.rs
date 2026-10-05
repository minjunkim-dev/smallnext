use smallnext_api::development_ai::{ActionState, AiInput, SubscriptionAi};
use std::io::Read;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let ai = match args.as_slice() {
        [] => SubscriptionAi::default(),
        [arg] if arg == "--enable-local-ai" => SubscriptionAi::for_local_development(),
        _ => return Err("usage: development-ai [--enable-local-ai]; JSON input on stdin".into()),
    };
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(32 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 32 * 1024 {
        return Err("input exceeds development limit".into());
    }
    let input: AiInput = serde_json::from_slice(&bytes).map_err(|_| "invalid development input")?;
    let mut state = ActionState::new(input.previous_proposals.last().cloned());
    let ticket = state.begin().map_err(|_| "request already pending")?;
    let outcome = ai.evaluate(&input, ticket).await;
    let disposition = outcome.disposition;
    let applied = state.finish(outcome);
    println!(
        "{}",
        serde_json::json!({"disposition": disposition, "applied": applied, "current_action": state.current(), "requested_model": smallnext_api::development_ai::MODEL, "actual_model_verified": false})
    );
    Ok(())
}

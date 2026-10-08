use super::{client, read_json, required};
use crate::development_ai::{
    AiInput, Disposition, MODEL, Proposal, validate_check, validate_proposal,
};
use serde::Serialize;
use serde_json::{Value, json};
use utoipa::ToSchema;

#[derive(Clone)]
pub(super) struct Provider {
    http: reqwest::Client,
    key: String,
    pub(super) endpoint: String,
    pub(super) context_tokens: u64,
    pub(super) output_tokens: u64,
    input_rate: u64,
    output_rate: u64,
}

#[derive(Clone, Serialize, ToSchema)]
pub struct Usage {
    role: String,
    input_tokens: u64,
    output_tokens: u64,
    cached_tokens: u64,
    cache_write_tokens: u64,
    reasoning_tokens: u64,
    cost_micro_usd: i64,
}

pub(super) struct Evaluation {
    pub result: Result<Proposal, Disposition>,
    pub usage: Vec<Usage>,
    pub charged: i64,
    pub overrun: bool,
}

impl Provider {
    pub(super) fn from_environment() -> Result<Self, &'static str> {
        // This gate does not prove availability. #47 records the operator's evidence.
        if required("AI_MODEL_CONFIRMED")? != "1" {
            return Err(
                "verify API model availability, context limit and pricing before enabling user AI",
            );
        }
        Ok(Self {
            http: client()?,
            key: required("OPENAI_API_KEY")?,
            endpoint: "https://api.openai.com/v1/responses".into(),
            context_tokens: number("AI_MODEL_CONTEXT_TOKENS", 2_000_000)?,
            output_tokens: number("AI_MAX_OUTPUT_TOKENS", 32_000)?,
            input_rate: number("AI_INPUT_MICRO_USD_PER_MILLION", 1_000_000_000)?,
            output_rate: number("AI_OUTPUT_MICRO_USD_PER_MILLION", 1_000_000_000)?,
        })
    }

    pub(super) fn role_ceiling(&self) -> i64 {
        // Reserve the VERIFIED full model input ceiling, not an unproven tokenizer estimate.
        self.cost(self.context_tokens, self.output_tokens)
    }

    fn cost(&self, input: u64, output: u64) -> i64 {
        (input * self.input_rate + output * self.output_rate).div_ceil(1_000_000) as i64
    }

    pub(super) async fn evaluate(&self, input: &AiInput, original: Value) -> Evaluation {
        let mut usage = Vec::new();
        let mut charged = 0;
        let mut overrun = false;
        let (generated, bill, exceeded) = self.call("generate", &original).await;
        charged += bill
            .as_ref()
            .map_or(self.role_ceiling(), |u| u.cost_micro_usd);
        overrun |= exceeded;
        if let Some(bill) = bill {
            usage.push(bill);
        }
        let generated = generated
            .and_then(|value| {
                serde_json::from_value::<Proposal>(value).map_err(|_| Disposition::InvalidProposal)
            })
            .and_then(|proposal| {
                validate_proposal(input, &proposal)?;
                Ok(proposal)
            });
        let result = match generated {
            Err(reason) => Err(reason),
            Ok(proposal) => {
                let (checked, bill, exceeded) = self
                    .call(
                        "check",
                        &json!({"original_request":original,"candidate":proposal}),
                    )
                    .await;
                charged += bill
                    .as_ref()
                    .map_or(self.role_ceiling(), |u| u.cost_micro_usd);
                overrun |= exceeded;
                if let Some(bill) = bill {
                    usage.push(bill);
                }
                checked.and_then(validate_check).map(|()| proposal)
            }
        };
        Evaluation {
            result,
            usage,
            charged,
            overrun,
        }
    }

    async fn call(
        &self,
        role: &str,
        payload: &Value,
    ) -> (Result<Value, Disposition>, Option<Usage>, bool) {
        let (instructions, schema) = match role {
            "generate" => (
                include_str!("../development_ai/generate.md"),
                include_str!("../development_ai/generate.json"),
            ),
            _ => (
                include_str!("../development_ai/check.md"),
                include_str!("../development_ai/check.json"),
            ),
        };
        let schema: Value = serde_json::from_str(schema).expect("committed schema");
        let body = json!({"model":MODEL,"instructions":instructions,"input":payload.to_string(),
            "reasoning":{"effort":"medium"},"max_output_tokens":self.output_tokens,
            "store":false,"background":false,"stream":false,"tools":[],"tool_choice":"none",
            "truncation":"disabled","text":{"format":{"type":"json_schema","name":role,"strict":true,"schema":schema}}});
        let response = self
            .http
            .post(&self.endpoint)
            .bearer_auth(&self.key)
            .json(&body)
            .send()
            .await;
        let response = match response {
            Err(error) => {
                return (
                    Err(if error.is_timeout() {
                        Disposition::TimedOut
                    } else {
                        Disposition::ConnectionLost
                    }),
                    None,
                    false,
                );
            }
            Ok(response) => response,
        };
        if response.status() == reqwest::StatusCode::TOO_MANY_REQUESTS {
            return (Err(Disposition::BudgetLimit), None, false);
        }
        let value = match read_json(response, 256 * 1024).await {
            Ok(value) => value,
            Err(()) => return (Err(Disposition::Failed), None, false),
        };
        if value["model"] != MODEL {
            // An unconfirmed model has no verified price or ceiling. Block this month.
            return (Err(Disposition::Failed), None, true);
        }
        let overrun = value["usage"]["input_tokens"]
            .as_u64()
            .is_some_and(|n| n > self.context_tokens)
            || value["usage"]["output_tokens"]
                .as_u64()
                .is_some_and(|n| n > self.output_tokens);
        let usage = self.usage(role, &value["usage"]);
        // Missing usage remains charged at the verified model's ceiling.
        if overrun || value["status"] != "completed" || !value["error"].is_null() {
            return (Err(Disposition::Failed), usage, overrun);
        }
        let Some(output) = value["output"].as_array() else {
            return (Err(Disposition::Failed), usage, false);
        };
        let messages: Vec<_> = output
            .iter()
            .filter(|item| item["type"] == "message")
            .collect();
        if output
            .iter()
            .any(|item| item["type"] != "message" && item["type"] != "reasoning")
            || messages.len() != 1
        {
            return (Err(Disposition::Failed), usage, false);
        }
        let message = messages[0];
        let Some(content) = message["content"].as_array() else {
            return (Err(Disposition::Failed), usage, false);
        };
        if message["role"] != "assistant"
            || message["status"] != "completed"
            || content.len() != 1
            || content[0]["type"] != "output_text"
        {
            return (Err(Disposition::Rejected), usage, false);
        }
        let result = content[0]["text"]
            .as_str()
            .filter(|text| text.len() <= 128 * 1024)
            .and_then(|text| serde_json::from_str(text).ok())
            .ok_or(Disposition::InvalidProposal);
        (result, usage, false)
    }

    fn usage(&self, role: &str, value: &Value) -> Option<Usage> {
        let input = value["input_tokens"].as_u64()?;
        let output = value["output_tokens"].as_u64()?;
        let cached = value["input_tokens_details"]["cached_tokens"].as_u64()?;
        let written = value["input_tokens_details"]["cache_write_tokens"]
            .as_u64()
            .unwrap_or(0);
        let reasoning = value["output_tokens_details"]["reasoning_tokens"].as_u64()?;
        if input > self.context_tokens
            || output > self.output_tokens
            || cached > input
            || written > input
            || reasoning > output
            || value["total_tokens"].as_u64()? != input.checked_add(output)?
        {
            return None;
        }
        Some(Usage {
            role: role.into(),
            input_tokens: input,
            output_tokens: output,
            cached_tokens: cached,
            cache_write_tokens: written,
            reasoning_tokens: reasoning,
            cost_micro_usd: self.cost(input, output),
        })
    }

    #[cfg(test)]
    pub(super) fn test_provider() -> Self {
        Self {
            http: client().unwrap(),
            key: "test-provider".into(),
            endpoint: "https://api.openai.com/v1/responses".into(),
            context_tokens: 20_000,
            output_tokens: 1_000,
            input_rate: 1_000_000,
            output_rate: 1_000_000,
        }
    }
}

pub(super) fn number(name: &str, ceiling: u64) -> Result<u64, &'static str> {
    let value = required(name)?
        .parse::<u64>()
        .map_err(|_| "invalid numeric AI configuration")?;
    if value == 0 || value > ceiling {
        return Err("AI configuration exceeds approved limit");
    }
    Ok(value)
}

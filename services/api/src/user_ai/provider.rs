use super::{client, read_json, required};
use crate::development_ai::{
    AiInput, Disposition, Proposal, generation_schema, model_instructions, validate_check,
    validate_proposal,
};
use serde::Serialize;
use serde_json::{Value, json};
use utoipa::ToSchema;

const MODEL: &str = "claude-haiku-5-5";
// Maximum long-context rates, including 1h cache writes. Reverify before API activation.
const CONTEXT_TOKENS: u64 = 1_000_000;
const INPUT_RATE_FLOOR: u64 = 1_000_000;
const OUTPUT_RATE_FLOOR: u64 = 2_500_000;

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
    reasoning_tokens: Option<u64>,
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
        let context_tokens = number("AI_MODEL_CONTEXT_TOKENS", CONTEXT_TOKENS)?;
        let input_rate = number("AI_INPUT_MICRO_USD_PER_MILLION", 1_000_000_000)?;
        let output_rate = number("AI_OUTPUT_MICRO_USD_PER_MILLION", 1_000_000_000)?;
        verify_limits(context_tokens, input_rate, output_rate)?;
        Ok(Self {
            http: client()?,
            key: required("ANTHROPIC_API_KEY")?,
            endpoint: "https://api.anthropic.com/v1/messages".into(),
            context_tokens,
            output_tokens: number("AI_MAX_OUTPUT_TOKENS", 128_000)?,
            input_rate,
            output_rate,
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
        let instructions = match model_instructions(role) {
            Ok(instructions) => instructions,
            Err(error) => return (Err(error), None, false),
        };
        let schema = match role {
            "generate" => include_str!("../development_ai/generate.json"),
            _ => include_str!("../development_ai/check.json"),
        };
        let mut schema: Value = serde_json::from_str(schema).expect("committed schema");
        if role == "generate" {
            schema = generation_schema(payload["request_kind"].as_str());
        }
        if role == "check" {
            // Messages JSON Schema does not support numeric bounds. Keep the exact domain as enum.
            schema["properties"]["criteria"]["items"] =
                json!({"type":"integer","enum":[1,2,3,4,5]});
        }
        let body = json!({"model":MODEL,"system":instructions,
            "messages":[{"role":"user","content":payload.to_string()}],
            "thinking":{"type":"adaptive"},"max_tokens":self.output_tokens,
            "stream":false,"tools":[],"service_tier":"standard_only",
            "output_config":{"effort":"xhigh","format":{"type":"json_schema","schema":schema}}});
        let response = self
            .http
            .post(&self.endpoint)
            .header("x-api-key", &self.key)
            .header("anthropic-version", "2023-06-01")
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
        let overrun = input_tokens(&value["usage"]).is_some_and(|n| n > self.context_tokens)
            || [
                "input_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ]
            .iter()
            .any(|key| {
                value["usage"][key]
                    .as_u64()
                    .is_some_and(|n| n > self.context_tokens)
            })
            || value["usage"]["output_tokens"]
                .as_u64()
                .is_some_and(|n| n > self.output_tokens)
            || value["usage"]["server_tool_use"]
                .as_object()
                .is_some_and(|counts| {
                    counts
                        .values()
                        .any(|count| count.as_u64().is_none_or(|n| n != 0))
                });
        let usage = self.usage(role, &value["usage"]);
        // Missing usage remains charged at the verified model's ceiling.
        if overrun
            || value["type"] != "message"
            || value["stop_reason"] != "end_turn"
            || !value["error"].is_null()
        {
            return (Err(Disposition::Failed), usage, overrun);
        }
        let Some(content) = value["content"].as_array() else {
            return (Err(Disposition::Failed), usage, false);
        };
        let texts: Vec<_> = content
            .iter()
            .filter(|item| item["type"] == "text")
            .collect();
        if value["role"] != "assistant"
            || !value["stop_details"].is_null()
            || content.iter().any(|item| {
                item["type"] != "text"
                    && item["type"] != "thinking"
                    && item["type"] != "redacted_thinking"
            })
            || texts.len() != 1
        {
            return (Err(Disposition::Rejected), usage, false);
        }
        let result = texts[0]["text"]
            .as_str()
            .filter(|text| text.len() <= 128 * 1024)
            .and_then(|text| serde_json::from_str(text).ok())
            .ok_or(Disposition::InvalidProposal);
        (result, usage, false)
    }

    fn usage(&self, role: &str, value: &Value) -> Option<Usage> {
        let input = input_tokens(value)?;
        let output = value["output_tokens"].as_u64()?;
        let cached = optional_tokens(value, "cache_read_input_tokens")?;
        let written = optional_tokens(value, "cache_creation_input_tokens")?;
        let reasoning = value["output_tokens_details"]["thinking_tokens"].as_u64();
        if input > self.context_tokens
            || output > self.output_tokens
            || cached > input
            || written > input
            || reasoning.is_some_and(|n| n > output)
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
            endpoint: "https://api.anthropic.com/v1/messages".into(),
            context_tokens: 20_000,
            output_tokens: 1_000,
            input_rate: 1_000_000,
            output_rate: 1_000_000,
        }
    }
}

fn optional_tokens(value: &Value, key: &str) -> Option<u64> {
    if value[key].is_null() {
        Some(0)
    } else {
        value[key].as_u64()
    }
}

fn verify_limits(context: u64, input_rate: u64, output_rate: u64) -> Result<(), &'static str> {
    if context != CONTEXT_TOKENS || input_rate < INPUT_RATE_FLOOR || output_rate < OUTPUT_RATE_FLOOR
    {
        return Err("Haiku full context and conservative pricing floors are required");
    }
    Ok(())
}

fn input_tokens(value: &Value) -> Option<u64> {
    value["input_tokens"]
        .as_u64()?
        .checked_add(optional_tokens(value, "cache_read_input_tokens")?)?
        .checked_add(optional_tokens(value, "cache_creation_input_tokens")?)
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn anthropic_usage_includes_all_input_and_thinking_without_inventing_unknown_counts() {
        let provider = Provider::test_provider();
        let mut value = json!({"input_tokens":7,"cache_read_input_tokens":3,
            "cache_creation_input_tokens":1,"output_tokens":7,
            "output_tokens_details":{"thinking_tokens":2}});
        let usage = provider.usage("generate", &value).expect("Messages usage");
        assert_eq!(usage.input_tokens, 11);
        assert_eq!(usage.cost_micro_usd, 18);
        assert_eq!(serde_json::to_value(&usage).unwrap()["reasoning_tokens"], 2);
        value
            .as_object_mut()
            .unwrap()
            .remove("output_tokens_details");
        assert!(serde_json::to_value(provider.usage("generate", &value).unwrap()).unwrap()["reasoning_tokens"].is_null());
        value["cache_read_input_tokens"] = json!(20_001);
        assert!(provider.usage("generate", &value).is_none());
        value["cache_read_input_tokens"] = json!(u64::MAX);
        assert!(provider.usage("generate", &value).is_none());
    }

    #[test]
    fn verified_haiku_reservation_fits_initial_budget_without_price_discounts() {
        assert!(verify_limits(CONTEXT_TOKENS, INPUT_RATE_FLOOR, OUTPUT_RATE_FLOOR).is_ok());
        assert!(verify_limits(CONTEXT_TOKENS - 1, INPUT_RATE_FLOOR, OUTPUT_RATE_FLOOR).is_err());
        assert!(verify_limits(CONTEXT_TOKENS, INPUT_RATE_FLOOR - 1, OUTPUT_RATE_FLOOR).is_err());
        assert!(verify_limits(CONTEXT_TOKENS, INPUT_RATE_FLOOR, OUTPUT_RATE_FLOOR - 1).is_err());
        let mut provider = Provider::test_provider();
        provider.context_tokens = CONTEXT_TOKENS;
        provider.output_tokens = 8192;
        provider.input_rate = INPUT_RATE_FLOOR;
        provider.output_rate = OUTPUT_RATE_FLOOR;
        assert_eq!(provider.role_ceiling() * 2, 2_040_960);
        assert!(provider.role_ceiling() * 2 <= 3_000_000);
    }
}

"""Report fixed failure categories without printing model messages or credentials."""

import json
import os
from pathlib import Path


SUBTYPES = {"success", "error_during_execution", "error_max_turns", "error_max_budget_usd",
            "error_max_structured_output_retries"}
SUBTYPE_CATEGORIES = {"error_max_turns": "turn_limit", "error_max_budget_usd": "quota",
                      "error_max_structured_output_retries": "invalid_request"}
SDK_ERRORS = {"authentication_failed": "authentication", "oauth_org_not_allowed": "authentication",
              "billing_error": "billing", "rate_limit": "quota", "overloaded": "provider",
              "invalid_request": "invalid_request", "model_not_found": "invalid_request",
              "server_error": "provider", "unknown": "unknown", "max_output_tokens": "output_limit"}
API_STATUSES = {400: "invalid_request", 401: "authentication", 402: "billing", 403: "permission",
                404: "invalid_request", 413: "invalid_request", 429: "quota", 500: "provider", 529: "provider"}


def summarize(messages):
    if not isinstance(messages, list):
        return {"category": "unavailable"}
    result_index = next(
        (index for index in range(len(messages) - 1, -1, -1)
         if isinstance(messages[index], dict) and messages[index].get("type") == "result"),
        None,
    )
    if result_index is None:
        return {"category": "unavailable"}
    result = messages[result_index]
    # SDK metadata only. Model prose, tool output, and free-form errors cannot establish a cause.
    subtype = result.get("subtype")
    subtype = subtype if isinstance(subtype, str) and subtype in SUBTYPES else "unknown"
    category = SUBTYPE_CATEGORIES.get(subtype, "unknown")
    status = result.get("api_error_status")
    status = status if type(status) is int and status in API_STATUSES else None
    sdk_error = None
    if result.get("is_error") is True:
        last_assistant = next(
            (item for item in reversed(messages[:result_index])
             if isinstance(item, dict) and item.get("type") == "assistant"), {},
        )
        error = last_assistant.get("error")
        if isinstance(error, str) and error in SDK_ERRORS:
            sdk_error = error
        if category == "unknown":
            category = API_STATUSES.get(status, SDK_ERRORS.get(sdk_error, "unknown"))
    turns = result.get("num_turns")
    return {
        "category": category,
        "subtype": subtype,
        "turns": turns if type(turns) is int and 0 <= turns <= 10000 else None,
        "sdk_error": sdk_error,
        "api_status": status,
    }


def main():
    try:
        path = Path(os.environ["REVIEW_EXECUTION_FILE"]).resolve()
        runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
        if not path.is_relative_to(runner_temp) or path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Invalid diagnostic file")
        report = summarize(json.loads(path.read_text(encoding="utf-8")))
    except (KeyError, OSError, ValueError, TypeError):
        report = {"category": "unavailable"}
    print("Claude failure summary: " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Report fixed failure categories without printing model messages or credentials."""

import json
import os
from pathlib import Path
import re


SUBTYPES = {"success", "error_during_execution", "error_max_turns", "error_max_budget_usd"}
CATEGORIES = (
    ("authentication", r"authenticat|invalid.api.key|invalid.token|token.expired|\b401\b"),
    ("quota", r"rate.limit|quota|credit.balance|usage.limit|out.of.credits|extra.usage|\b429\b"),
    ("turn_limit", r"max.turns|maximum.turns|turn.limit"),
    ("permission", r"permission.denied|not.authorized|forbidden|\b403\b"),
    ("isolation", r"bubblewrap|bwrap|sandbox"),
    ("network", r"ECONN|ENOTFOUND|fetch.failed|network.error|timed.out"),
)


def summarize(messages):
    if not isinstance(messages, list):
        return {"category": "unavailable"}
    result = next(
        (item for item in reversed(messages) if isinstance(item, dict) and item.get("type") == "result"),
        {},
    )
    # Inspect only the final result. Never include prompts, tool output, or message text in the report.
    text = result.get("result", "")
    if not isinstance(text, str):
        text = ""
    errors = result.get("errors", [])
    if isinstance(errors, list):
        text += " ".join(error for error in errors if isinstance(error, str))
    category = next((name for name, pattern in CATEGORIES if re.search(pattern, text, re.I)), "unknown")
    subtype = result.get("subtype")
    turns = result.get("num_turns")
    return {
        "category": category,
        "subtype": subtype if subtype in SUBTYPES else "unknown",
        "turns": turns if type(turns) is int and 0 <= turns <= 10000 else None,
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

#!/usr/bin/env python3
"""Check PR conventions, shared instructions, and feature flag metadata."""

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TYPES = "feat|fix|refactor|perf|test|docs|build|ci|chore|revert"
TITLE = re.compile(rf"^({TYPES})(\([a-z0-9]+(?:[-_][a-z0-9]+)*\))?!?: [a-z][^\r\n]*$")
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
LETTER_SLUG = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
BRANCH = re.compile(rf"^(?:({TYPES})/[1-9][0-9]*-{SLUG}|(?:docs|build|ci|chore)/{LETTER_SLUG})$")
BOT_BRANCH = re.compile(r"^(?:claude|codex|dependabot)/[a-z0-9][a-z0-9._/-]*$")
ISSUE_REF = re.compile(r"\b(?:Closes|Fixes|Resolves|Refs)\s+#[1-9][0-9]*\b", re.IGNORECASE)


def validate_pr(title, branch, body=""):
    errors = []
    match = TITLE.fullmatch(title)
    # Dependabot names long packages in full ("bump androidx.compose:compose-bom from ... in /apps/android").
    too_long = len(title) > 72 and not branch.startswith("dependabot/")
    if not match or too_long or title.endswith("."):
        errors.append("PR title: use Conventional Commits, lowercase description, <=72 characters, no final period")
    if not BRANCH.fullmatch(branch) and not BOT_BRANCH.fullmatch(branch):
        errors.append("Branch: use <type>/<issue>-<slug>; docs/build/ci/chore may omit the issue")
    if match and match[1] in {"feat", "fix", "refactor", "perf", "test", "revert"} and not ISSUE_REF.search(body):
        errors.append("PR body: link the implementation issue with Refs #N or Closes #N")
    return errors


def positive_integer(value):
    return type(value) is int and value > 0


def validate_flags(registry, today=None):
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    if not isinstance(registry, dict) or type(registry.get("version")) is not int or registry["version"] != 1 or not isinstance(registry.get("flags"), list):
        return ["Feature flags: expected version 1 and a flags array"]
    errors, keys = [], set()
    for index, flag in enumerate(registry["flags"]):
        prefix = f"Feature flag {index}"
        if not isinstance(flag, dict):
            errors.append(f"{prefix}: expected an object")
            continue
        key = flag.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", key) or key in keys:
            errors.append(f"{prefix}: key must be unique snake_case")
        elif key:
            keys.add(key)
        phase = flag.get("phase")
        if phase not in ("development", "released") or type(flag.get("default")) is not bool:
            errors.append(f"{prefix}: expected a valid phase and boolean default")
        if phase == "development" and flag.get("default") is not False:
            errors.append(f"{prefix}: unfinished features must default to OFF")
        if phase == "released" and not positive_integer(flag.get("release_issue")):
            errors.append(f"{prefix}: link the release approval issue")
        if not isinstance(flag.get("owner"), str) or not flag["owner"].strip() or not positive_integer(flag.get("issue")):
            errors.append(f"{prefix}: owner and issue are required")
        try:
            remove_by = date.fromisoformat(flag.get("remove_by", ""))
            if remove_by < today:
                errors.append(f"{prefix}: remove_by has expired; remove the flag or record a new date")
        except (TypeError, ValueError):
            errors.append(f"{prefix}: remove_by must be YYYY-MM-DD")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", action="store_true", help="Read PR metadata from GITHUB_EVENT_PATH")
    args = parser.parse_args()
    errors = []
    if (ROOT / "CLAUDE.md").read_text() != "@AGENTS.md\n":
        errors.append("CLAUDE.md must contain only @AGENTS.md and a newline")
    if not (ROOT / "AGENTS.md").is_file():
        errors.append("AGENTS.md is required")
    try:
        errors.extend(validate_flags(json.loads((ROOT / "config/feature-flags.json").read_text())))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"Feature flags: {error}")
    if args.pr:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        pr = event["pull_request"]
        errors.extend(validate_pr(pr["title"], pr["head"]["ref"], pr.get("body") or ""))
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("PASS: shared agent instructions, feature flag metadata" + (", PR conventions" if args.pr else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check PR conventions, and optional shared instructions and feature flags.

Title, branch, issue link, and body sections are the shared rules. AGENTS.md and
feature flags stay on unless .github/workflow-policy.json turns them off, so a
consumer that copies this file keeps those checks. The pull request body is parsed
and never executed.
"""

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from pr_author import parse_author, text_of

ROOT = Path(__file__).resolve().parents[1]
TYPES = "feat|fix|refactor|perf|test|docs|build|ci|chore|revert"
TITLE = re.compile(rf"^({TYPES})(\([a-z0-9]+(?:[-_][a-z0-9]+)*\))?!?: (?:[a-z]|[가-힣])[^\r\n]*$")
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
LETTER_SLUG = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
BRANCH = re.compile(rf"^(?:({TYPES})/[1-9][0-9]*-{SLUG}|(?:docs|build|ci|chore)/{LETTER_SLUG})$")
ISSUE_REF = re.compile(r"\b(?:Closes|Fixes|Resolves|Refs)\s+#[1-9][0-9]*\b", re.IGNORECASE)
ISSUE_TYPES = {"feat", "fix", "refactor", "perf", "test", "revert"}
HEADERS = ("Summary", "Evidence", "Merge Danger")
# Current names. The deprecated pair is the previous name for the same decision.
DOOR_VALUES = {"되돌리기 쉬움", "되돌리기 어려움"}
DEPRECATED_DOOR_VALUES = {"양쪽 문", "한쪽 문"}
DOORS = DOOR_VALUES | DEPRECATED_DOOR_VALUES
DEFAULT_BOT_PREFIXES = ("claude", "codex", "dependabot")
CONFIG_NAME = ".github/workflow-policy.json"
DEPENDABOT = "dependabot[bot]"


def validate_pr(title, branch, body="", author="", bot_prefixes=None):
    errors = []
    match = TITLE.fullmatch(title)
    # Dependabot names long packages in full. The PR author is set by GitHub.
    prefixes = DEFAULT_BOT_PREFIXES if bot_prefixes is None else tuple(bot_prefixes)
    too_long = len(title) > 72 and author != DEPENDABOT
    if not match or too_long or title.endswith("."):
        errors.append("PR title: use Conventional Commits, lowercase or Hangul description, <=72 characters, no final period")
    bot = re.compile(rf"^(?:{'|'.join(re.escape(item) for item in prefixes)})/[a-z0-9][a-z0-9._/-]*$") if prefixes else None
    if not BRANCH.fullmatch(branch) and not (bot and bot.fullmatch(branch)):
        errors.append("Branch: use <type>/<issue>-<slug>; docs/build/ci/chore may omit the issue")
    if match and match[1] in ISSUE_TYPES and not ISSUE_REF.search(body or ""):
        errors.append("PR body: link the implementation issue with Refs #N or Closes #N")
    return errors


def validate_body(body, author=""):
    """Required sections. Dependabot keeps the title and branch rules and skips these."""
    if author == DEPENDABOT:
        return []
    text = text_of(body)
    errors = []
    for name in HEADERS:
        if not any(line.strip() == f"## {name}" for line in text.split("\n")):
            errors.append(f"PR body: missing ## {name}")
    # The field name stays Door:. A value must match exactly, including the deprecated names.
    doors = [line[len("Door:"):].strip() for line in text.split("\n") if line.startswith("Door:")]
    if len(doors) != 1 or doors[0] not in DOORS:
        errors.append("PR body: Door must be 되돌리기 쉬움 or 되돌리기 어려움")
    _, _, author_errors = parse_author(text)
    errors.extend(author_errors)
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


def load_config(root):
    """Defaults keep a consumer's AGENTS.md and feature-flag checks. A file may turn them off."""
    config = {
        "require_agents_md": True,
        "reject_claude_md": True,
        "feature_flags": "config/feature-flags.json",
        "bot_branch_prefixes": list(DEFAULT_BOT_PREFIXES),
        "protected_paths": [
            "scripts/workflow_policy.py", "scripts/pr_author.py", ".github/workflow-policy.json",
        ],
    }
    path = root / CONFIG_NAME
    if not path.exists() and not path.is_symlink():
        return config
    found = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(found, dict):
        raise ValueError("workflow policy config must be an object")
    unknown = set(found) - set(config)
    if unknown:
        raise ValueError("unknown workflow policy keys: " + ", ".join(sorted(unknown)))
    for key in ("require_agents_md", "reject_claude_md"):
        if key in found:
            if type(found[key]) is not bool:
                raise ValueError(f"{key} must be a boolean")
            config[key] = found[key]
    if "feature_flags" in found:
        value = found["feature_flags"]
        if value is False or value is None:
            config["feature_flags"] = False
        elif isinstance(value, str) and value and ".." not in value.split("/") and not value.startswith(("/", "\\")):
            config["feature_flags"] = value
        else:
            raise ValueError("feature_flags must be false or a relative path")
    if "bot_branch_prefixes" in found:
        prefixes = found["bot_branch_prefixes"]
        if not isinstance(prefixes, list) or not prefixes or any(
                not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", item) for item in prefixes):
            raise ValueError("bot_branch_prefixes must be lowercase names")
        config["bot_branch_prefixes"] = prefixes
    if "protected_paths" in found:
        value = found["protected_paths"]
        required = set(config["protected_paths"])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item or ".." in item.split("/") for item in value) or required - set(value):
            raise ValueError("protected_paths must include the convention scripts")
        config["protected_paths"] = value
    return config


def checked_tree(value):
    """Files are read from this path. It is not imported or executed."""
    if value is None:
        return ROOT
    path = Path(value)
    if path.is_absolute() or not value or ".." in path.parts:
        raise ValueError("root must be a relative path")
    return path


def readable_file(tree, relative):
    """A regular file under tree. Symlinks are not followed."""
    current = tree
    if current.is_symlink():
        return None
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            return None
    return current if current.is_file() else None


def _symlink_inside(tree, relative):
    current = tree
    if current.is_symlink():
        return True
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            return True
        if not current.exists():
            return False
    return False


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", action="store_true", help="Read PR metadata from GITHUB_EVENT_PATH")
    parser.add_argument("--root", help="Tree to read for AGENTS.md, CLAUDE.md, and feature flags. Config stays beside the checker.")
    args = parser.parse_args(argv)
    try:
        config = load_config(ROOT)
        tree = checked_tree(args.root)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"FAIL: workflow policy config: {error}")
        return 1
    errors = []
    if config["reject_claude_md"]:
        claude = tree / "CLAUDE.md"
        if claude.exists() or claude.is_symlink():
            errors.append("Use AGENTS.md only; remove CLAUDE.md")
    if config["require_agents_md"] and readable_file(tree, "AGENTS.md") is None:
        errors.append("AGENTS.md is required")
    flags = config["feature_flags"]
    if flags:
        flag_file = readable_file(tree, flags)
        if flag_file is None and _symlink_inside(tree, flags):
            errors.append("Feature flags: refusing to follow a symlink")
        else:
            try:
                if flag_file is None:
                    raise OSError("missing")
                errors.extend(validate_flags(json.loads(flag_file.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"Feature flags: {error}")
    if args.pr:
        # The event file is JSON. The body is untrusted text and is only parsed.
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        pr = event["pull_request"]
        login = pr["user"]["login"]
        body = pr.get("body") or ""
        errors.extend(validate_pr(pr["title"], pr["head"]["ref"], body, login, config["bot_branch_prefixes"]))
        errors.extend(validate_body(body, login))
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    parts = []
    if config["reject_claude_md"] or config["require_agents_md"]:
        parts.append("shared agent instructions")
    if flags:
        parts.append("feature flag metadata")
    if args.pr:
        parts.append("PR conventions")
    print("PASS: " + ", ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())

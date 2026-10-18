#!/usr/bin/env python3
"""Read GitHub settings and report drift; never change repository settings."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def differences(expected, actual, path=""):
    """Compare required fields; omitted required fields are drift, not false."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path or "<root>"]
        result = []
        for key, value in expected.items():
            name = f"{path}.{key}" if path else key
            if key not in actual:
                result.append(name)
            else:
                result.extend(differences(value, actual[key], name))
        return result
    if type(expected) is not type(actual):
        return [path]
    if isinstance(expected, list):
        # API ordering is irrelevant; duplicates and extra entries still differ.
        expected = sorted(json.dumps(item, sort_keys=True) for item in expected)
        actual = sorted(json.dumps(item, sort_keys=True) for item in actual)
    return [] if expected == actual else [path]


def read_api(endpoint):
    result = subprocess.run(
        ["gh", "api", "--method", "GET", endpoint],
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def codeql_source_drift(profile):
    """Offline PR check: the pinned main blob must match the checked-out workflow,
    and every github/codeql-action step must use one commit (init and analyze fail apart)."""
    source = profile["expected"].get("codeql_main_source")
    if source is None:  # default setup: no workflow file to pin
        return []
    data = (ROOT / source["path"]).read_bytes()
    blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    result = [] if blob == source["sha"] else ["codeql_main_source.sha"]
    refs = set(codeql_action_refs(data.decode("utf-8")))
    pinned = len(refs) == 1 and re.fullmatch(r"[0-9a-f]{40}", next(iter(refs)))
    return result + ([] if pinned or not refs else ["codeql_workflow.action_pins"])


def codeql_action_refs(text):
    """Refs of github/codeql-action steps, from block-style step `uses:` keys.
    `run:` block text and `with:` inputs sit deeper than a step's keys, so they are skipped.
    Any other step-level mention of github/codeql-action (flow style, folded values) yields an unpinned
    ref, so unusual syntax fails the check instead of passing it."""
    refs, keys, block = [], None, None
    for raw in text.splitlines():
        line = "" if raw.lstrip().startswith("#") else raw.split(" #", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if block is not None and indent > block:
            continue
        block = None
        item = re.match(r"(\s*-\s+)(\S.*)", line)
        if item:  # a sequence item; its mapping keys start after "-" and the spaces
            indent = keys = len(item[1])
            line = item[2]
        match = re.match(r"[\"']?([\w-]+)[\"']?\s*:\s*(.*)", line.strip())
        key, value = (match[1], match[2].strip().strip("\"'")) if match else (None, "")
        if value[:1] in ("|", ">"):
            block = indent
        if key == "uses" and indent == keys and value.startswith("github/codeql-action/"):
            refs.append(value.partition("@")[2].lower())
        elif indent == keys and ("github/codeql-action/" in line or (key == "uses" and value[:1] in ("|", ">"))):
            refs.append("unrecognized")  # step-level syntax this scanner does not read
    return refs


# Required controls cannot disappear when someone edits the baseline.
REQUIRED_FIELDS = {
    "repository": "default_branch visibility allow_merge_commit allow_rebase_merge allow_squash_merge allow_auto_merge delete_branch_on_merge allow_update_branch squash_merge_commit_title squash_merge_commit_message security_and_analysis.dependabot_security_updates.status security_and_analysis.secret_scanning.status security_and_analysis.secret_scanning_push_protection.status",
    "protection": "required_status_checks.strict required_status_checks.checks required_pull_request_reviews.required_approving_review_count required_pull_request_reviews.dismiss_stale_reviews required_pull_request_reviews.require_code_owner_reviews required_pull_request_reviews.require_last_push_approval enforce_admins.enabled required_linear_history.enabled required_conversation_resolution.enabled allow_force_pushes.enabled allow_deletions.enabled lock_branch.enabled",
    "rulesets": "",
    "actions": "enabled allowed_actions sha_pinning_required",
    "allowed_actions": "github_owned_allowed verified_allowed patterns_allowed",
    "workflow_token": "default_workflow_permissions can_approve_pull_request_reviews",
    "fork_policy": "approval_policy",
    "immutable_releases": "enabled",
    "dependabot_alerts": "enabled",
    "codeql": "state",
    "codeql_workflow": "path state",
    "codeql_main_source": "path type sha",
}
# Only advanced setup has a workflow file; default setup must not list it.
ADVANCED_CODEQL = {"codeql_workflow", "codeql_main_source"}
STRING_FIELDS = {
    "default_branch", "visibility", "squash_merge_commit_title", "squash_merge_commit_message",
    "status", "allowed_actions", "default_workflow_permissions", "approval_policy", "state", "path", "type", "sha",
}


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("Baseline must be an object")
    expected = profile.get("expected")
    if not isinstance(expected, dict):
        raise ValueError("Baseline must include every required control")
    codeql = expected.get("codeql")
    default_setup = isinstance(codeql, dict) and codeql.get("state") == "configured"
    required = set(REQUIRED_FIELDS) - ADVANCED_CODEQL if default_setup else set(REQUIRED_FIELDS)
    if set(expected) != required:
        raise ValueError("Baseline must include every required control")
    for control, fields in REQUIRED_FIELDS.items():
        if control not in required:
            continue
        value = expected[control]
        if control == "rulesets":
            if not isinstance(value, list):
                raise ValueError("Rulesets must be a list")
            continue
        if not isinstance(value, dict):
            raise ValueError(f"Invalid control: {control}")
        for field in fields.split():
            current = value
            for part in field.split("."):
                if not isinstance(current, dict) or part not in current:
                    raise ValueError(f"Missing required setting: {control}.{field}")
                current = current[part]
            leaf = field.split(".")[-1]
            kind = str if leaf in STRING_FIELDS else int if leaf == "required_approving_review_count" else list if leaf in {"checks", "patterns_allowed"} else bool
            if type(current) is not kind:
                raise ValueError(f"Invalid setting type: {control}.{field}")
            if kind is str and not current:
                raise ValueError(f"Empty setting: {control}.{field}")
        checks = value["required_status_checks"]["checks"] if control == "protection" else None
        if checks is not None and (not checks or any(
            not isinstance(check, dict) or not isinstance(check.get("context"), str)
            or not check["context"] or type(check.get("app_id")) is not int
            for check in checks
        )):
            raise ValueError("Required checks must include names and App IDs")
    if type(profile.get("repository_id")) is not int or profile["repository_id"] <= 0:
        raise ValueError("Invalid repository ID")


def audit(profile, read=None):
    validate_profile(profile)
    read = read_api if read is None else read
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("Unsupported settings baseline version")
    repo = profile["repository"]
    branch = profile["default_branch"]
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repo) or repo.split("/")[-1] in {".", ".."}:
        raise ValueError("Invalid repository identity")
    if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", branch) or ".." in branch or branch.endswith("."):
        raise ValueError("Invalid baseline branch")
    prefix = f"repos/{repo}"
    metadata = read(prefix)
    if not isinstance(metadata, dict) or metadata["id"] != profile["repository_id"] or metadata["full_name"] != repo:
        raise ValueError("Repository identity mismatch")
    paths = {
        "protection": f"branches/{branch}/protection",
        "rulesets": "rulesets",
        "actions": "actions/permissions",
        "allowed_actions": "actions/permissions/selected-actions",
        "workflow_token": "actions/permissions/workflow",
        "fork_policy": "actions/permissions/fork-pr-contributor-approval",
        "immutable_releases": "immutable-releases",
        "codeql": "code-scanning/default-setup",
        "codeql_workflow": "actions/workflows/codeql.yml",
        "codeql_main_source": f"contents/.github/workflows/codeql.yml?ref={branch}",
    }
    result = []
    for name, expected in profile["expected"].items():
        if name == "repository":
            actual = metadata
        elif name == "dependabot_alerts":
            # A successful GET returns 204. Permission or API errors must fail.
            read(f"{prefix}/vulnerability-alerts")
            actual = {"enabled": True}
        else:
            if name not in paths:
                raise ValueError(f"Unsupported settings endpoint: {name}")
            actual = read(f"{prefix}/{paths[name]}")
        result.extend(differences(expected, actual, name))
    return result


def main():
    try:
        profile = json.loads((ROOT / ".github/repository-settings.json").read_text())
        drift = audit(profile)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"UNVERIFIED: GitHub settings lookup failed ({type(error).__name__})", file=sys.stderr)
        return 2
    if drift:
        print("DRIFT: " + ", ".join(drift))
        return 1
    print(f"PASS: {profile['repository']} settings match baseline; no writes performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

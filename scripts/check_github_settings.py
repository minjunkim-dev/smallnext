#!/usr/bin/env python3
"""Read GitHub settings and report drift; never change repository settings."""

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


def audit(profile, read=read_api):
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("Unsupported settings baseline version")
    repo = profile["repository"]
    branch = profile["default_branch"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repo) or repo.split("/")[-1] in {".", ".."}:
        raise ValueError("Invalid repository identity")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", branch) or ".." in branch or branch.endswith("."):
        raise ValueError("Invalid baseline branch")
    prefix = f"repos/{repo}"
    metadata = read(prefix)
    if metadata["id"] != profile["repository_id"] or metadata["full_name"] != repo:
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
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"UNVERIFIED: GitHub settings lookup failed ({type(error).__name__})", file=sys.stderr)
        return 2
    if drift:
        print("DRIFT: " + ", ".join(drift))
        return 1
    print(f"PASS: {profile['repository']} settings match baseline; no writes performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

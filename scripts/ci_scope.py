#!/usr/bin/env python3
"""Select required checks from the full PR diff; unknown history checks everything."""

import json
import os
from pathlib import Path
import subprocess


PROJECTS = ("api", "container", "ios", "android")
SCOPED_FILES = {
    ".gitignore": (),
    ".editorconfig": (),
    ".github/dependabot.yml": (),
    ".github/workflows/project-checks.yml": PROJECTS,
    ".github/workflows/repository-checks.yml": (),
    ".github/workflows/pr-policy.yml": (),
    ".github/workflows/agent-review.yml": (),
    ".github/workflows/api-checks.yml": ("api",),
    ".github/workflows/api-container.yml": ("container",),
    ".github/workflows/ios-checks.yml": ("ios",),
    ".github/workflows/android-checks.yml": ("android",),
    "scripts/ci_scope.py": PROJECTS,
    "scripts/test_ci_scope.py": PROJECTS,
    "scripts/check_repository.py": (),
    "scripts/workflow_policy.py": (),
    "scripts/test_workflow_policy.py": (),
    "scripts/review_context.py": (),
    "scripts/review_failure.py": (),
    "scripts/test_review_failure.py": (),
    "scripts/review_report.py": (),
    "scripts/test_review_report.py": (),
    "scripts/check_api_spec.py": ("api",),
    "scripts/ios_simulator.py": ("ios",),
    "rust-toolchain.toml": ("api", "container"),
    "Makefile": PROJECTS,
    ".dockerignore": ("container",),
    ".env.example": ("container",),
}


def scopes(event):
    base = event["pull_request"]["base"]["sha"] if "pull_request" in event else event.get("before")
    if not base or set(base) == {"0"}:
        return dict.fromkeys(PROJECTS, True)
    try:
        # A move between projects must select both the deleted and added paths.
        paths = subprocess.check_output(
            ["git", "diff", "--no-renames", "--name-only", base, "HEAD"], text=True,
        ).splitlines()
    except subprocess.CalledProcessError:
        return dict.fromkeys(PROJECTS, True)
    selected = dict.fromkeys(PROJECTS, False)
    for path in paths:
        if path.endswith(".md") or path.startswith("docs/"):
            continue
        if path in SCOPED_FILES:
            projects = SCOPED_FILES[path]
        elif path.startswith((".github/workflows/", ".github/actions/", "scripts/", "contracts/")):
            projects = PROJECTS
        elif path.startswith("services/api/"):
            projects = ("api",) if path.startswith("services/api/tests/") else ("api", "container")
        elif path.startswith("infra/"):
            projects = ("container",)
        elif path.startswith("apps/ios/"):
            projects = ("ios",)
        elif path.startswith("apps/android/"):
            projects = ("android",)
        else:
            projects = PROJECTS
        for project in projects:
            selected[project] = True
    return selected


if __name__ == "__main__":
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    selected = scopes(event)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for name, enabled in selected.items():
            output.write(f"{name}={str(enabled).lower()}\n")
    print(json.dumps(selected))

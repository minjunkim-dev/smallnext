#!/usr/bin/env python3
"""Select independent project checks; missing Git history selects all checks."""

import json
import os
from pathlib import Path
import subprocess


def scopes(event):
    if "pull_request" in event:
        base = event["pull_request"]["base"]["sha"]
    else:
        base = event.get("before")
    if not base or set(base) == {"0"}:
        return {"api": True, "ios": True, "android": True}
    try:
        paths = subprocess.check_output(
            ["git", "diff", "--name-only", base, "HEAD"], text=True,
        ).splitlines()
    except subprocess.CalledProcessError:
        return {"api": True, "ios": True, "android": True}
    common = any(
        path.startswith((".github/workflows/", "scripts/", "contracts/"))
        or path in {"Makefile", "rust-toolchain.toml"}
        for path in paths
    )
    return {
        "api": common or any(
            path.startswith(("services/api/", "infra/"))
            or path in {".dockerignore", ".env.example"}
            for path in paths
        ),
        "ios": common or any(path.startswith("apps/ios/") for path in paths),
        "android": common or any(path.startswith("apps/android/") for path in paths),
    }


if __name__ == "__main__":
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    selected = scopes(event)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for name, enabled in selected.items():
            output.write(f"{name}={str(enabled).lower()}\n")
    print(json.dumps(selected))

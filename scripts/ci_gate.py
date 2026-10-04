#!/usr/bin/env python3
"""Require valid scope outputs and the expected result for every project job."""

import json
import os
import sys


PROJECTS = ("api", "container", "ios", "android")


def check_results(needs):
    if not isinstance(needs, dict):
        raise ValueError("needs must be an object")
    scope = needs.get("scope")
    if not isinstance(scope, dict) or scope.get("result") != "success":
        raise ValueError("scope did not succeed")
    outputs = scope.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("scope outputs are missing")
    for project in PROJECTS:
        selected = outputs.get(project)
        if selected not in ("true", "false"):
            raise ValueError(f"{project}: scope output must be true or false")
        job = needs.get(project)
        expected = "success" if selected == "true" else "skipped"
        if not isinstance(job, dict) or job.get("result") != expected:
            raise ValueError(f"{project}: expected {expected}")


if __name__ == "__main__":
    try:
        check_results(json.loads(os.environ.get("NEEDS_JSON", "")))
    except ValueError as error:
        print(f"Project checks failed: {error}", file=sys.stderr)
        sys.exit(1)
    print("Selected project checks succeeded; unselected projects were skipped.")

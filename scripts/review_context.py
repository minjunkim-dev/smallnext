#!/usr/bin/env python3
"""Authorize review requests before the workflow receives Claude credentials."""

import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen


def api_get(repo, endpoint):
    request = Request(
        f"https://api.github.com/repos/{repo}/{endpoint}",
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def review_request(event_name, event, repo, get):
    sender = event.get("sender", {})
    if sender.get("type") != "User":
        return None, "Bot events do not trigger reviews"
    login = sender.get("login", "")
    if not re.fullmatch(r"[A-Za-z0-9-]+", login):
        return None, "Invalid actor"
    permission = get(f"collaborators/{login}/permission").get("permission")
    if permission not in {"admin", "maintain", "write"}:
        return None, "Only repository writers may request reviews"
    if event.get("action") == "labeled" and event.get("label", {}).get("name") != "ai:review":
        return None, "Only ai:review requests a label-triggered review"
    mode = "review"
    if event_name == "pull_request_target":
        kind, number = "pr", event["pull_request"]["number"]
    elif event_name == "issues":
        kind, number = "issue", event["issue"]["number"]
    elif event_name == "issue_comment":
        command = (event.get("comment", {}).get("body") or "").strip()
        if not re.match(r"^@claude\s+(?:security\s+)?review\b", command, re.IGNORECASE):
            return None, "Supported commands: @claude review or @claude security review"
        mode = "security" if re.match(r"^@claude\s+security\s+review\b", command, re.IGNORECASE) else "review"
        kind = "pr" if event["issue"].get("pull_request") else "issue"
        number = event["issue"]["number"]
    else:
        return None, "Unsupported event"
    if type(number) is not int or number < 1:
        return None, "Invalid issue or PR number"
    issue = get(f"issues/{number}")
    if issue.get("state") != "open" or any(label["name"] == "ai:skip" for label in issue.get("labels", [])):
        return None, "Closed or ai:skip item"
    if kind == "issue" and issue.get("pull_request"):
        return None, "Use kind pr for a pull request"
    sha = "none"
    if kind == "pr":
        pr = get(f"pulls/{number}")
        if pr.get("draft") or pr.get("state") != "open":
            return None, "Draft or closed PR"
        if pr.get("head", {}).get("repo", {}).get("full_name") != repo:
            return None, "Fork PRs require a manual review without secrets"
        if pr.get("base", {}).get("ref") != "main":
            return None, "Only main-targeted PRs are reviewed"
        sha = pr["head"]["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            return None, "Invalid head SHA"
    return {"kind": kind, "number": str(number), "sha": sha, "mode": mode}, "Authorized"


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    result, reason = review_request(os.environ["GITHUB_EVENT_NAME"], event, repo, lambda endpoint: api_get(repo, endpoint))
    print(reason)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"run={'true' if result else 'false'}\n")
        for key, value in (result or {}).items():
            output.write(f"{key}={value}\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"Review authorization: {reason}.\n")


if __name__ == "__main__":
    main()

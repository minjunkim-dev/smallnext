#!/usr/bin/env python3
"""Validate Project checks through read-only GitHub APIs from the default branch."""

import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote

from ci_scope import select
from review_context import api_get


WORKFLOW_PATH = ".github/workflows/project-checks.yml"
PROJECT_JOBS = {
    "api": ("api / verify",),
    "container": ("container / image",),
    "ios": ("ios / test",),
    "android": ("android / build", "android / device-tests"),
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "Invalid SHA")
    return value


def pages(get, endpoint, key=None):
    items = []
    for page in range(1, 32):
        separator = "&" if "?" in endpoint else "?"
        response = get(f"{endpoint}{separator}per_page=100&page={page}")
        batch = response[key] if key else response
        require(isinstance(batch, list), "Invalid API list")
        items.extend(batch)
        if len(batch) < 100:
            if key:
                require(len(items) == response["total_count"], "Incomplete API list")
            return items
    raise ValueError("API list exceeds supported size; cannot accept incomplete results")


def validate_run(run, event_run, repo, workflow):
    require(run["repository"]["full_name"] == repo, "Wrong run repository")
    require(run["workflow_id"] == workflow["id"] and run["path"] == WORKFLOW_PATH,
            "Wrong workflow ID or path")
    for key in ("id", "workflow_id", "path", "event", "head_sha", "head_branch", "run_attempt"):
        require(run[key] == event_run[key], f"Stale or mismatched run {key}")
    sha(run["head_sha"])
    require(type(run["run_attempt"]) is int and run["run_attempt"] > 0, "Invalid attempt")
    require(run["status"] == "completed", "Run is not completed")


def aggregate(event, repo, get):
    require(event["repository"]["full_name"] == repo and
            event["repository"]["default_branch"] == "main", "Wrong event repository or default branch")
    event_run = event["workflow_run"]
    run_id = event_run["id"]
    require(type(run_id) is int and run_id > 0, "Invalid run ID")
    workflow = get("actions/workflows/project-checks.yml")
    require(workflow["path"] == WORKFLOW_PATH, "Wrong configured workflow path")
    run = get(f"actions/runs/{run_id}")
    validate_run(run, event_run, repo, workflow)
    evidence = {"verdict": "out_of_scope", "run_id": run_id, "attempt": run["run_attempt"],
                "workflow_id": workflow["id"], "head_sha": run["head_sha"]}
    if run["event"] != "pull_request":
        return dict(evidence, reason="Only pull_request runs provide merge evidence")
    if run["head_repository"]["full_name"] != repo:
        return dict(evidence, reason="Fork PR is outside the initial rollout")

    open_prs = pages(get, "pulls?state=open&base=main")
    same_branch = [pr for pr in open_prs if pr["head"]["repo"] and
                   pr["head"]["repo"]["full_name"] == repo and
                   pr["head"]["ref"] == run["head_branch"]]
    if not same_branch:
        return dict(evidence, reason="No open same-repository PR; closed or deleted branch is not merge evidence")
    matches = [pr for pr in same_branch if pr["head"]["sha"] == run["head_sha"]]
    require(len(matches) == 1, "Stale head or ambiguous open PR association")
    pr = get(f"pulls/{matches[0]['number']}")
    require(pr["state"] == "open" and pr["head"]["sha"] == run["head_sha"] and
            pr["head"]["ref"] == run["head_branch"] and pr["head"]["repo"]["full_name"] == repo and
            pr["base"]["ref"] == "main" and pr["base"]["repo"]["full_name"] == repo,
            "PR changed or is outside the trusted scope")
    base = sha(pr["base"]["sha"])
    require(get("branches/main")["commit"]["sha"] == base, "PR base is not current main")

    files = pages(get, f"pulls/{pr['number']}/files")
    require(len(files) == pr["changed_files"], "Incomplete PR diff")
    paths = []
    for file in files:
        paths.append(file["filename"])
        if file.get("previous_filename"):
            paths.append(file["previous_filename"])
    selected = select(paths)
    jobs = pages(get, f"actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", "jobs")
    expected = {"scope": "success", "Project checks": "success"}
    for project, names in PROJECT_JOBS.items():
        expected.update(dict.fromkeys(names, "success") if selected[project] else {project: "skipped"})
    names = [job["name"] for job in jobs]
    require(len(names) == len(set(names)), "Duplicate job names")
    missing = expected.keys() - set(names)
    require(not missing, "Required jobs missing from latest attempt; re-run all jobs")
    require(set(names) == expected.keys(), "Unexpected job inventory; review workflow definitions")
    for job in jobs:
        require(job["run_id"] == run_id and job["run_attempt"] == run["run_attempt"] and
                job["head_sha"] == run["head_sha"], "Wrong job run, attempt or SHA")
        require(job["status"] == "completed" and job["conclusion"] == expected[job["name"]],
                f"{job['name']}: expected {expected[job['name']]}")
    require(run["conclusion"] == "success", "Source run failed or was cancelled")

    latest = get(f"actions/workflows/{workflow['id']}/runs?event=pull_request&branch="
                 f"{quote(run['head_branch'], safe='')}&head_sha={run['head_sha']}&per_page=1")
    require(latest["workflow_runs"] and latest["workflow_runs"][0]["id"] == run_id, "A newer source run exists")
    fresh_run = get(f"actions/runs/{run_id}")
    validate_run(fresh_run, event_run, repo, workflow)
    require(fresh_run["conclusion"] == "success", "Source result changed during collection")
    fresh_pr = get(f"pulls/{pr['number']}")
    require(fresh_pr["state"] == "open" and
            all(fresh_pr[side][key] == pr[side][key] for side in ("head", "base") for key in ("sha", "ref")) and
            all(fresh_pr[side]["repo"]["full_name"] == repo for side in ("head", "base")) and
            get("branches/main")["commit"]["sha"] == base,
            "PR head or base changed during collection")
    return dict(evidence, verdict="accepted", pr=pr["number"], base_branch="main", base_sha=base,
                head_branch=run["head_branch"], selected=selected,
                jobs=[{key: job[key] for key in ("id", "name", "conclusion")} for job in jobs])


def main():
    evidence = {"verdict": "rejected"}
    try:
        require(os.environ["GITHUB_EVENT_NAME"] == "workflow_run", "Only workflow_run is supported")
        repo = os.environ["GITHUB_REPOSITORY"]
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo), "Invalid repository")
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        evidence.update(trigger_run_id=event["workflow_run"]["id"],
                        trigger_attempt=event["workflow_run"]["run_attempt"])
        evidence = aggregate(event, repo, lambda endpoint: api_get(repo, endpoint))
    except (ValueError, KeyError, TypeError, OSError) as error:
        evidence["reason"] = str(error)
    evidence.update(aggregation_run_id=os.environ["GITHUB_RUN_ID"],
                    aggregation_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
                    policy_sha=os.environ["GITHUB_SHA"])
    report = json.dumps(evidence, indent=2, ensure_ascii=True)
    print(report)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"## Trusted CI aggregation\n\n```json\n{report}\n```\n")
    return 1 if evidence["verdict"] == "rejected" else 0


if __name__ == "__main__":
    sys.exit(main())

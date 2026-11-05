#!/usr/bin/env python3
"""Re-run Review status after the owner approval comment changes.

An issue_comment run is not a pull request check. The previous success stays
until the pull_request_target run for this head is re-run, or until a newer
failing check named Review status is posted on that head. This does not write
review/independent or review/security, and it does not read the comment body.
issue_comment has no branch filter. A pull request whose base is not the
default branch posts nothing, so that head is not turned red for the pull
request that does target the default branch.
"""

from datetime import datetime, timezone
import json
import os
import subprocess
import sys

CHECK_NAME = "Review status"
PAGE_LIMIT = 20


def comment_triggers(is_pull_request, state, author, owner):
    """Same rule as the workflow `if`. A fork's author is not the base repository owner."""
    return bool(is_pull_request) and state == "open" and bool(owner) and author == owner


def matches(run, number, sha):
    """Match the run's own head_sha. A populated pull_requests list must name this pull request.
    pull_requests[].head.sha is not used: it can move to the current head and select an older run."""
    if (run or {}).get("head_sha") != sha:
        return False
    pulls = (run or {}).get("pull_requests") or []
    if not pulls:
        return True
    return any(pull.get("number") == number for pull in pulls)


def plan(runs, number, sha):
    """Newest-first runs for one head.

    ('rerun', id) replaces the latest success. ('wait', None) means a newer run
    for this head is still going, so an older success must not be refreshed yet.
    ('missing', None) means this list does not contain the head: the caller posts
    a failing check when the list is also complete.
    """
    for run in runs or []:
        if not matches(run, number, sha):
            continue
        if run.get("status") != "completed":
            return "wait", None
        return "rerun", run.get("id")
    return "missing", None


def fail_closed_body(sha, now=None):
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "name": CHECK_NAME,
        "head_sha": sha,
        "status": "completed",
        "conclusion": "failure",
        "started_at": stamp,
        "completed_at": stamp,
        "output": {
            "title": "Owner approval changed",
            "summary": "The owner approval comment no longer matches this head, "
                       "and the previous Review status run could not be re-run.",
        },
    }


def collect(pages):
    """Flatten newest-first pages. The second value is False when the last page is full."""
    runs = []
    complete = True
    for batch in pages:
        runs.extend(batch)
        if len(batch) == 100:
            complete = False
        else:
            complete = True
    if pages and len(pages[-1]) == 100:
        complete = False
    return runs, complete


def _run(command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, check=True, **kwargs)


def fetch_pages(repo, execute):
    pages = []
    for page in range(1, PAGE_LIMIT + 1):
        result = execute([
            "gh", "api",
            f"repos/{repo}/actions/workflows/review-status.yml/runs"
            f"?event=pull_request_target&per_page=100&page={page}",
        ])
        batch = (json.loads(result.stdout or "{}").get("workflow_runs") or [])
        pages.append(batch)
        if len(batch) < 100:
            break
    return pages


def targets_default(pull):
    """True when this pull request's base ref is that repository's default branch.
    Raises when either name cannot be read. The base repository is the pull request target."""
    base = pull.get("base") if isinstance(pull, dict) else None
    ref = base.get("ref") if isinstance(base, dict) else None
    target = base.get("repo") if isinstance(base, dict) else None
    default = target.get("default_branch") if isinstance(target, dict) else None
    if not isinstance(ref, str) or ref == "" or not isinstance(default, str) or default == "":
        raise ValueError("default branch")
    return ref == default


def main(env=None, execute=None, pages=None):
    env = env if env is not None else os.environ
    number = env.get("PR_NUMBER") or ""
    repo = env.get("REPO") or ""
    if not number.isdigit() or not repo:
        print("bad pull request number", file=sys.stderr)
        return 1
    execute = execute or _run
    listed = execute(["gh", "api", f"repos/{repo}/pulls/{number}"])
    try:
        pull = json.loads(listed.stdout or "")
        on_default = targets_default(pull)
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        print("bad pull request", file=sys.stderr)
        return 1
    if not on_default:
        print(f"side base; not posting a check for {number}", file=sys.stderr)
        return 0
    sha = ((pull.get("head") or {}).get("sha") or "").strip()
    if len(sha) != 40 or any(char not in "0123456789abcdefABCDEF" for char in sha):
        print("bad head sha", file=sys.stderr)
        return 1
    runs, complete = collect(pages if pages is not None else fetch_pages(repo, execute))
    action, run_id = plan(runs, int(number), sha)
    if action == "wait":
        print("matching run still in progress", file=sys.stderr)
        return 2
    reason = None
    if action == "rerun":
        # Pages are newest first, so this is the latest run for the head even when later pages remain.
        try:
            execute(["gh", "run", "rerun", str(run_id), "--repo", repo])
        except subprocess.CalledProcessError as error:
            print(f"gh run rerun failed: {error}", file=sys.stderr)
            reason = "gh run rerun failed"
        else:
            return 0
    body = json.dumps(fail_closed_body(sha))
    execute(["gh", "api", "--method", "POST", f"repos/{repo}/check-runs", "--input", "-"], input=body)
    if reason is None:
        reason = "the run list was cut off" if not complete else "no matching run"
    print(f"{reason} for {number} at {sha}; posted a failing check", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

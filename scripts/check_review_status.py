#!/usr/bin/env python3
"""Fail when a pull request head lacks the review statuses its changed paths need (POLICY.md §5).
Paths only: content signals stay a reviewer judgement. On a 1-person profile, review/independent
and review/security count only when creator.login is the repository owner or a login in
STATUS_ACTORS (empty until the server app exists). Another creator is failure, not a missing
context, so an older success is not carried over it. The same account still cannot tell a person
from an agent. A team profile does not look at the creator.
A base update creates a new head SHA. Carry hashes the diff and the full post-change blob id of
each changed file. Line numbers do not count. Another file changing on the base leaves this file's
blob in place, so that success still covers the head. The same file changing, even when the diff
only shifts line numbers, is a new blob and is reviewed again. The function name after the second
@@ stays in the hash: it records which function git named, and the blob id is what separates files
where that name is missing or shared. A diff --git header that names one path twice is split in
the middle, so a directory named "svc b" is not read as the root file. A rename or copy takes the
new path from rename to or copy to. Anything else is not carried. Only the parent trees of changed
paths are read. A gitlink that is itself the changed path contributes its commit id. Reuse is still
only a process record, and it uses the same creator rule.
A 1-person pull request that changes a POLICY.md §10 gate path also needs the repository owner's
approval comment on this head. That comment is not reused from an older head. An edited comment
is not approval: updated_at must equal created_at, and lastEditedAt must be null. A same-second
edit keeps the timestamp strings equal and is still not approval. Post a new comment.
The first line must be the current prefix or the deprecated prefix, then the full head SHA.
A comment rerun does not parse the body. It runs this checker, so both prefixes share this match,
and an edit re-run drops the edited comment.
The pull request body is parsed for the review evidence table. It is never executed.
The pull request base ref must be the repository default branch, and the event base SHA must be
that branch or an ancestor of it. A pull request with a different base is not evidence."""

import base64
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

from pr_author import parse_author

INDEPENDENT = "review/independent"
SECURITY = "review/security"
# Not a commit status. The job fails with this name when the owner comment is missing.
# A status posted under this name does not count: the same account can post one without the comment.
OWNER = "review/owner-approval"
# Not a commit status. The job fails with this name when the evidence table does not match this head.
EVIDENCE = "review/evidence"
# Not a commit status. The job fails with this name when this pull request does not target the
# repository default branch. A status posted under this name does not count.
BASE_REF = "review/base-branch"
DEPENDABOT = "dependabot[bot]"
WEB_FLOW = "web-flow"
TEAM_LINE = "프로필: 팀"
# Solo-profile logins that may post review/independent and review/security, besides the
# repository owner. Empty until the server app exists. This file runs from the default
# branch, so a pull request cannot add a login. A team profile does not read this tuple.
STATUS_ACTORS = ()
# Exact first-line prefixes. The second is deprecated and means the same approval.
APPROVAL_LINE = re.compile(
    r"(?:되돌리기 어려움 승인:|한쪽 문 승인:)"
    r"[ \t]*([0-9a-fA-F]{40})(?:[ \t].*)?\Z")
FORCE_PUSHES = "graphql://force-push-befores/"
PRIOR_LIMIT = 40
PROJECT_PATHS = ".github/trust-boundary-paths"
# POLICY.md §5 common paths. A pattern without "/" matches the file name at any depth.
COMMON_PATHS = (
    ".github/workflows/**", ".github/actions/**", ".github/repository-settings.json", ".github/dependabot.yml",
    ".github/dependabot.yaml", ".github/CODEOWNERS", ".github/repo-baseline.json", ".github/workflow-policy.json",
    PROJECT_PATHS, "scripts/check_*.py",
    "scripts/workflow_policy.py", "scripts/pr_author.py", "scripts/rerun_review_status.py",
    ".claude/settings.json", ".claude/hooks/**", ".claude/agents/**", ".claude/commands/**", ".agents/skills/**",
    ".claude/skills/**", ".mcp.json", "Dockerfile", ".env*",
)
# POLICY.md §10 gate paths. A change here needs the 1-person owner comment unless the Dependabot
# version-only exception applies. Other hard-to-reverse decisions (money, account, migration) are not in this list.
ONE_WAY_PATHS = (
    ".github/workflows/**", "templates/review-status.yml", "templates/pr-policy.yml",
    "scripts/check_review_status.py", "scripts/workflow_policy.py", "scripts/pr_author.py",
    "scripts/rerun_review_status.py", ".github/workflow-policy.json",
    "templates/review-status-policy.json", ".github/repository-settings.json", "templates/repository-settings.json",
)
# Dependency manifests and lockfiles; a project adds other ecosystems to PROJECT_PATHS.
DEPENDENCY_FILES = (
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "pyproject.toml", "poetry.lock", "uv.lock", "Pipfile",
    "Pipfile.lock", "requirements*.txt", "Gemfile", "Gemfile.lock", "Package.swift", "Package.resolved",
    "Podfile", "Podfile.lock", "build.gradle", "build.gradle.kts", "gradle.lockfile", "libs.versions.toml",
    "pubspec.yaml", "pubspec.lock", "composer.json", "composer.lock",
)
# A number or hash right after a word character, "." or "-" is part of a name (pkg-2), so changing it needs Security. That
# also catches file names such as x-1.0.0.tgz, so an npm or yarn lockfile bump needs Security too: the safe side.
# shortcut: any other number counts as a version, so a Dependabot line changing only a number passes; upgrade if
# Dependabot ever changes more than versions.
VERSION = re.compile(r"(?:sha\d+[-:]|h1:)[A-Za-z0-9+/=]+|(?<![\w.-])[0-9a-f]{7,}\b"
                     r"|(?<![\w.-])v?\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?")


def read_api(endpoint):
    if endpoint.startswith(FORCE_PUSHES):
        repo, number = endpoint[len(FORCE_PUSHES):].rsplit("/", 1)
        return force_push_befores(repo, number)
    comments = comment_list_target(endpoint)
    if comments is not None:
        return approval_comment_pages(*comments)
    paged = ["--paginate", "--slurp"] if "per_page" in endpoint else []
    result = subprocess.run(["gh", "api", "--method", "GET", endpoint, *paged],
                            capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


def read_diff_api(endpoint):
    result = subprocess.run(
        ["gh", "api", "--method", "GET", "-H", "Accept: application/vnd.github.diff", endpoint],
        capture_output=True, text=True, check=True, timeout=60)
    return result.stdout


def force_push_befores(repo, number):
    """SHAs the pull request head pointed at before a rebase, newest first.
    None when the timeline cannot be read. An empty list means it was read and has no force pushes."""
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$name:String!,$number:Int!){"
        "repository(owner:$owner,name:$name){pullRequest(number:$number){"
        "timelineItems(last:20,itemTypes:[HEAD_REF_FORCE_PUSHED_EVENT]){"
        "nodes{... on HeadRefForcePushedEvent{createdAt beforeCommit{oid}}}}}}}"
    )
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}",
             "-f", f"name={name}", "-F", f"number={int(number)}"],
            capture_output=True, text=True, check=True, timeout=60)
        nodes = json.loads(result.stdout)["data"]["repository"]["pullRequest"]["timelineItems"]["nodes"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    return force_push_events(nodes)


def force_push_events(nodes):
    """Newest-first {createdAt, oid}. None when an event has no before SHA or no time."""
    dated = []
    for node in nodes or []:
        oid = ((node or {}).get("beforeCommit") or {}).get("oid")
        created = (node or {}).get("createdAt")
        if not oid or not created:
            return None
        dated.append((created, oid))
    dated.sort(reverse=True)
    return [{"createdAt": created, "oid": oid} for created, oid in dated]


def force_push_oids(nodes):
    """Newest-first SHAs. None when an event has no beforeCommit oid, so that head is not skipped."""
    events = force_push_events(nodes)
    if events is None:
        return None
    return [event["oid"] for event in events]


def full_oid(value):
    """True for a full Git object id. An abbreviated index line is not one."""
    return isinstance(value, str) and len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value)


def git_header_path(line):
    """('path', path) when diff --git names one path on both sides, split at the middle.
    ('rename', None) when the sides differ, so the new path comes from rename to or copy to.
    ('bad', None) when the header is quoted or not diff --git a/. A last ' b/' is not a split:
    a/svc b/package.json b/svc b/package.json is the file svc b/package.json, not package.json."""
    prefix = "diff --git "
    if not isinstance(line, str) or not line.startswith(prefix + "a/"):
        return "bad", None
    body = line[len(prefix):]
    if (len(body) - 5) % 2 == 0:
        length = (len(body) - 5) // 2
        path = body[2:2 + length]
        if length > 0 and body == f"a/{path} b/{path}":
            return "path", path
    return "rename", None


def destination_path(line, current):
    """New path after a rename to or copy to line. current when this line is not one of those.
    False when the path is empty, quoted, or a different path was already chosen."""
    dest = None
    for prefix in ("rename to ", "copy to "):
        if line.startswith(prefix):
            dest = line[len(prefix):]
            break
    if dest is None:
        return current
    if dest == "" or dest.startswith('"') or (current is not None and current != dest):
        return False
    return dest


def diff_identity(diff, blobs=None):
    """SHA-256 of the diff body plus each changed file's post-change blob id.
    blobs maps the path after the change to a full blob SHA, or None when that path was deleted.
    The numbers in an @@ line do not count. The text after the second @@ stays: it is the function
    git named. The blob id is the whole file, so a move still differs when that name is missing,
    shared, or cut off, and when the surrounding lines are blank. A lone CR is part of the line.
    None blobs means the caller is comparing diff text only. A provided map that misses a path, or
    a blob that is not a full id, is not safe to treat as unchanged."""
    if diff is None:
        return None
    # GitHub's diff is LF. A bare CR is not a line ending here: stripping it would hide an injected CR.
    text = diff.replace("\r\n", "\n")
    stripped = text.lstrip()
    if not stripped:
        return "empty"
    if stripped.startswith("{") or stripped.startswith("["):
        return None
    chunks = []
    current = new_path = None
    deleted = False
    header, body = [], []
    binary = False
    in_hunk = False

    def flush():
        nonlocal current, new_path, deleted, header, body, binary
        if current is None:
            return True
        if new_path is None:
            return False
        chunks.append((current, new_path, deleted, binary, tuple(header), tuple(body)))
        current = new_path = None
        deleted = binary = False
        header, body = [], []
        return True

    for line in text.split("\n"):
        if line.startswith("diff --git "):
            if not flush():
                return None
            status, path = git_header_path(line)
            if status == "bad":
                return None
            current = line
            new_path = path if status == "path" else None
            in_hunk = False
            continue
        if current is None:
            if line.strip() == "":
                continue
            return None
        if line.startswith("index "):
            # Abbreviated blob ids in this line are not the post-change id.
            continue
        # A hunk line "+ ++ /dev/null" is content. Only the header marks a deleted file.
        if not in_hunk and (line.startswith("deleted file mode ") or line == "+++ /dev/null"):
            deleted = True
        if line.startswith(("new file mode ", "deleted file mode ", "old mode ", "new mode ",
                            "rename from ", "rename to ", "copy from ", "copy to ")):
            chosen = destination_path(line, new_path)
            if chosen is False:
                return None
            new_path = chosen
            header.append(line)
            continue
        # "--- a/file" is a header. A removed line "-- note" is also "--- note", so only skip headers
        # before the first hunk.
        if line.startswith("@@"):
            in_hunk = True
            # Numbers sit between the markers. The function git named follows the second @@.
            body.append("@@" + line.split("@@", 2)[-1])
            continue
        if not in_hunk and line.startswith(("--- ", "+++ ", "similarity index ", "dissimilarity index ")):
            continue
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            binary = True
            body.append(line)
            continue
        if line.startswith(("+", "-", "\\")) or (in_hunk and line.startswith(" ")):
            body.append(line)
            continue
        if line == "" or line.startswith(" "):
            continue
        return None
    if not flush() or not chunks:
        return None
    blob_lines = []
    if blobs is not None:
        if not isinstance(blobs, dict):
            return None
        for _, path, removed, _binary, _header, _body in chunks:
            if path not in blobs:
                return None
            oid = blobs[path]
            if removed:
                if oid is not None:
                    return None
                blob_lines.append("blob\tdeleted\t" + path)
                continue
            if not full_oid(oid):
                return None
            blob_lines.append("blob\t" + path + "\t" + oid.lower())
    chunks.sort(key=lambda item: item[0])
    lines = []
    for path, _new_path, _removed, _binary, kept_header, kept_body in chunks:
        lines.append(path)
        lines.extend(kept_header)
        lines.extend(kept_body)
    lines.extend(sorted(blob_lines))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def path_oids(repo, sha, paths, read):
    """Post-change id for each path. Only parent trees of those paths are read.
    A blob contributes its blob id. A gitlink on the path itself contributes its commit id.
    A gitlink anywhere else is not opened. Raises when a needed tree is truncated or an id is short."""
    if not paths:
        return {}
    commit = read(f"repos/{repo}/commits/{sha}")
    root = ((commit.get("commit") or {}).get("tree") or {}).get("sha") if isinstance(commit, dict) else None
    if not full_oid(root):
        raise ValueError("tree")
    cache = {}

    def load(oid):
        if oid not in cache:
            data = read(f"repos/{repo}/git/trees/{oid}")
            if not isinstance(data, dict) or data.get("truncated") or not isinstance(data.get("tree"), list):
                raise ValueError("tree")
            entries = {}
            for item in data["tree"]:
                if not isinstance(item, dict):
                    raise ValueError("tree")
                name = item.get("path")
                kind = item.get("type")
                child = item.get("sha")
                if not isinstance(name, str) or name == "" or "/" in name or not full_oid(child):
                    raise ValueError("tree")
                if kind not in ("blob", "tree", "commit"):
                    raise ValueError("tree")
                entries[name] = (kind, child.lower())
            cache[oid] = entries
        return cache[oid]

    found = {}
    for path in paths:
        parts = path.split("/")
        if any(part == "" for part in parts):
            raise ValueError("tree")
        current = root
        matched = False
        for index, part in enumerate(parts):
            item = load(current).get(part)
            if item is None:
                raise ValueError("tree")
            kind, oid = item
            last = index == len(parts) - 1
            if kind == "tree" and not last:
                current = oid
                continue
            if last and kind in ("blob", "commit"):
                found[path] = oid
                matched = True
                break
            raise ValueError("tree")
        if not matched:
            raise ValueError("tree")
    return found


def changed_blobs(repo, sha, diff, read):
    """Post-change id for each path in the diff. None on a path means that file was deleted.
    A gitlink contributes its commit id."""
    specs = []
    current = new_path = None
    deleted = False
    in_hunk = False

    def flush():
        nonlocal current, new_path, deleted, in_hunk
        if current is None:
            return
        if new_path is None:
            raise ValueError("blobs")
        specs.append((new_path, deleted))
        current = new_path = None
        deleted = False
        in_hunk = False

    for line in diff.replace("\r\n", "\n").split("\n"):
        if line.startswith("diff --git "):
            flush()
            status, path = git_header_path(line)
            if status == "bad":
                raise ValueError("blobs")
            current = line
            new_path = path if status == "path" else None
            continue
        if current is None:
            continue
        if line.startswith(("rename to ", "copy to ")):
            chosen = destination_path(line, new_path)
            if chosen is False:
                raise ValueError("blobs")
            new_path = chosen
        if line.startswith("@@"):
            in_hunk = True
        if not in_hunk and (line.startswith("deleted file mode ") or line == "+++ /dev/null"):
            deleted = True
    flush()
    if not specs:
        raise ValueError("blobs")
    needed = [path for path, removed in specs if not removed]
    found = {path: None for path, removed in specs if removed}
    for path, oid in path_oids(repo, sha, needed, read).items():
        found[path] = oid
    if any(not removed and not full_oid(found.get(path)) for path, removed in specs):
        raise ValueError("blobs")
    return found


def matches(path, patterns):
    name = path.rsplit("/", 1)[-1]
    # With "/" a pattern is a path from the root, also read literally (in app/[id]/route.ts, [id] is no glob).
    rooted = (pattern.lstrip("/") for pattern in patterns if "/" in pattern)
    return (any(path == pattern or fnmatch.fnmatchcase(path, pattern)
                or path.startswith(pattern.removesuffix("/**") + "/") for pattern in rooted)
            or any(name == pattern or fnmatch.fnmatchcase(name, pattern) for pattern in patterns if "/" not in pattern))


def project_paths(repo, base, read):
    try:
        found = read(f"repos/{repo}/contents/{PROJECT_PATHS}?ref={base}")
    except subprocess.CalledProcessError as error:
        if "404" in (error.stderr or ""):
            return ()
        raise
    lines = base64.b64decode(found["content"]).decode("utf-8").splitlines()
    # CODEOWNERS spellings work too: /src/auth/ means src/auth/**, and /auth stays a root path.
    return tuple(re.sub(r"/$", "/**", line.strip()) for line in lines
                 if line.strip() and not line.startswith("#"))


def only_versions(entry):
    """True when a file's diff replaces lines with the same lines apart from version and hash values."""
    is_workflow = entry["filename"].startswith(".github/workflows/")
    if not is_workflow and not matches(entry["filename"], DEPENDENCY_FILES):
        return False
    lines = [line for line in entry.get("patch", "").splitlines() if line[:1] in ("-", "+")]
    if not lines or (is_workflow and not all(re.match(r"[-+]\s*(-\s+)?uses:", line) for line in lines)):
        return False
    normal = [VERSION.sub("V", line[1:]) for line in lines]
    return (sorted(text for line, text in zip(lines, normal) if line[0] == "-")
            == sorted(text for line, text in zip(lines, normal) if line[0] == "+"))


def is_hash(token):
    return re.fullmatch(r"(?:sha\d+[-:]|h1:)[A-Za-z0-9+/=]+|[0-9a-fA-F]{7,}", token) is not None


def _token_at(body, start, end):
    while start > 0 and (body[start - 1].isalnum() or body[start - 1] in "+/=_-"):
        start -= 1
    while end < len(body) and (body[end].isalnum() or body[end] in "+/=_-"):
        end += 1
    return body[start:end]


def line_majors(line, workflow):
    """Major numbers on one diff line. None means a uses: line has no # vN comment and no @vN tag.
    A digit inside a commit hash is not a major. Gate-path templates use the same rule as workflows."""
    body = line[1:]
    if workflow or "uses:" in body:
        found = [int(number) for number in re.findall(r"(?:#\s*v|@v)(\d+)", body, re.IGNORECASE)]
        return found or None
    found = []
    for match in re.finditer(r"(?<![\w.-])v?(\d+)(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?", body, re.IGNORECASE):
        if is_hash(match.group(0)) or is_hash(_token_at(body, match.start(), match.end())):
            continue
        found.append(int(match.group(1)))
    return found


def major_change(files):
    """True when a gate-path version move is a new major, or a workflow pin does not say its major.
    Review-status exemption is unchanged. This only refuses the owner-comment exemption (POLICY.md §10)."""
    for entry in files:
        name = entry.get("filename") or ""
        previous = entry.get("previous_filename") or ""
        if not matches(name, ONE_WAY_PATHS) and not matches(previous, ONE_WAY_PATHS):
            continue
        workflow = name.startswith(".github/workflows/") or previous.startswith(".github/workflows/")
        removed, added = [], []
        for line in entry.get("patch", "").splitlines():
            if line[:1] not in "-+":
                continue
            found = line_majors(line, workflow)
            if found is None:
                return True
            (removed if line[0] == "-" else added).extend(found)
        if sorted(removed) != sorted(added):
            return True
    return False


def dependabot_bump(pull, commits, files):
    """POLICY.md §5 exception: Dependabot's own commits, changing only versions and hashes.
    An author login follows the commit email and a signature only matches the committer, so both
    must show GitHub made the commit: web-flow as committer, verified. A person's amend fails this."""
    return (pull["user"]["login"] == DEPENDABOT
            and all((commit.get("author") or {}).get("login") == DEPENDABOT
                    and (commit.get("committer") or {}).get("login") == WEB_FLOW
                    and commit["commit"]["verification"]["verified"] for commit in commits)
            and all(only_versions(entry) for entry in files))


def approval_sha(body):
    """Full SHA when the first line is exactly one approval prefix plus that SHA. None otherwise."""
    if not isinstance(body, str) or body == "":
        return None
    # GitHub's web UI stores comment bodies with CRLF. A leftover CR is not whitespace in APPROVAL_LINE.
    found = APPROVAL_LINE.fullmatch(re.split(r"\r\n|\n|\r", body, maxsplit=1)[0])
    if not found:
        return None
    return found.group(1).lower()


def same_login(left, right):
    return isinstance(left, str) and isinstance(right, str) and left.casefold() == right.casefold()


def one_way(files, truncated):
    """True when a gate path changed, or the file list is short so a gate path could be hidden."""
    if truncated:
        return True
    return any(matches(entry.get(key) or "", ONE_WAY_PATHS)
               for entry in files for key in ("filename", "previous_filename"))


def profile_line_changes(files):
    """True when a diff adds or removes the team line, or that diff cannot be read.
    The base file decides the profile, so a pull request must not be able to opt out without the comment."""
    for entry in files:
        names = {entry.get("filename") or "", entry.get("previous_filename") or ""}
        if "AGENTS.md" not in names:
            continue
        patch = entry.get("patch")
        if not isinstance(patch, str):
            return True
        for line in patch.splitlines():
            if line[:1] in "+-" and line[1:].strip() == TEAM_LINE:
                return True
    return False


def blob_has_team_line(repo, ref, read):
    """True when that ref's AGENTS.md has the exact team line. A missing file does not."""
    try:
        found = read(f"repos/{repo}/contents/AGENTS.md?ref={ref}")
    except subprocess.CalledProcessError as error:
        if "404" in (error.stderr or ""):
            return False
        raise
    if not isinstance(found, dict) or "content" not in found:
        raise ValueError("AGENTS.md")
    text = base64.b64decode(found["content"]).decode("utf-8")
    return any(line.strip() == TEAM_LINE for line in text.splitlines())


def team_profile(repo, base, read):
    """The profile comes from the base branch. The pull request head cannot opt out."""
    return blob_has_team_line(repo, base, read)


def pinned_change(repo, base, head, read):
    """Files and commits for this base...head. None files means the compare is too large to trust.
    The open pull request's current file list can move after the event SHA and is not used here."""
    try:
        found = read(f"repos/{repo}/compare/{base}...{head}")
    except subprocess.CalledProcessError as error:
        if "406" in (error.stderr or ""):
            return None, None
        raise
    if not isinstance(found, dict):
        raise ValueError("compare")
    files = found.get("files")
    commits = found.get("commits")
    # Compare returns at most 300 files and 250 commits. A full list is not a complete diff.
    if not isinstance(files, list) or len(files) >= 300:
        return None, None
    if not isinstance(commits, list) or len(commits) >= 250:
        commits = None
    return files, commits


def touches_agents(files):
    return any((entry.get("filename") or "") == "AGENTS.md" or (entry.get("previous_filename") or "") == "AGENTS.md"
               for entry in files)


def default_base(repo, pull, read):
    """Default branch name when this pull request targets it. None for another base.
    A pull request with a different base is not evidence. Raises when either name cannot be read."""
    info = read(f"repos/{repo}")
    default = info.get("default_branch") if isinstance(info, dict) else None
    base = pull.get("base") if isinstance(pull, dict) else None
    ref = base.get("ref") if isinstance(base, dict) else None
    if not isinstance(default, str) or default == "" or not isinstance(ref, str) or ref == "":
        raise ValueError("default branch")
    if ref != default:
        print(f"review status: base {ref} is not the default branch {default}")
        return None
    return default


def event_base_on_default(repo, base, default, read):
    """True when the event base SHA is the default branch tip or an ancestor of it.
    compare(base...default) is ahead when that branch has moved past this SHA, and identical
    at the tip. behind or diverged means the SHA is not on the branch. A rerun keeps the
    original BASE_SHA, so retargeting onto the default branch must not pass the old SHA."""
    found = read(f"repos/{repo}/compare/{base}...{default}")
    if not isinstance(found, dict):
        raise ValueError("base branch")
    status = found.get("status")
    if status in ("ahead", "identical"):
        return True
    if status in ("behind", "diverged"):
        print(f"review status: event base {base} is not on the default branch {default} ({status})")
        return False
    raise ValueError("base branch")


def repository_owner(repo, read):
    info = read(f"repos/{repo}")
    owner = (info.get("owner") or {}).get("login") if isinstance(info, dict) else None
    if not isinstance(owner, str) or owner == "":
        raise ValueError("repository owner")
    return owner


def status_actors(repo, read):
    """Owner plus STATUS_ACTORS. Blank entries are not logins. Solo profile only."""
    extra = tuple(login for login in STATUS_ACTORS if isinstance(login, str) and login != "")
    return (repository_owner(repo, read), *extra)


def status_actor(status):
    creator = status.get("creator") if isinstance(status, dict) else None
    login = creator.get("login") if isinstance(creator, dict) else None
    if not isinstance(login, str) or login == "":
        return None
    return login


def reviewed_state(status, allowed):
    """State that counts for one review context.

    allowed is None on a team profile: the creator is not checked.
    On a 1-person profile, a creator outside allowed is failure. Combined status keeps
    the newest state per context, so dropping that status would look like a missing
    context and carry could reuse an older success over a newer rejection."""
    if allowed is None:
        return status["state"]
    actor = status_actor(status)
    if any(same_login(actor, login) for login in allowed):
        return status["state"]
    print(f"review status untrusted {status.get('context')} from {actor or 'unknown'} is not success")
    return "failure"


def comment_unedited(comment):
    """True when the comment was not edited.

    updated_at must be the same string as created_at. REST timestamps are whole seconds,
    so a same-second edit can keep those strings equal. last_edited_at is GraphQL
    lastEditedAt: null means GitHub recorded no edit, and a missing key is not approval.
    includes_created_edit true means the history contains an edit."""
    if not isinstance(comment, dict):
        return False
    created = comment.get("created_at")
    updated = comment.get("updated_at")
    if not (isinstance(created, str) and created != "" and created == updated):
        return False
    if "last_edited_at" not in comment or comment.get("last_edited_at") is not None:
        return False
    return comment.get("includes_created_edit") is not True


def comment_list_target(endpoint):
    """(repo, number) when endpoint is the issue-comment list. None otherwise."""
    parts = endpoint.split("/")
    if (len(parts) != 6 or parts[0] != "repos" or parts[3] != "issues"
            or parts[5] != "comments?per_page=100" or not parts[4].isdigit()):
        return None
    return f"{parts[1]}/{parts[2]}", parts[4]


def comment_record(node):
    """One issue comment from GraphQL. Raises when the edit fields are missing."""
    if not isinstance(node, dict):
        raise ValueError("approval comments")
    if "lastEditedAt" not in node or "includesCreatedEdit" not in node:
        raise ValueError("approval comments")
    author = node.get("author")
    login = author.get("login") if isinstance(author, dict) else None
    return {
        "user": {"login": login},
        "body": node.get("body"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "last_edited_at": node.get("lastEditedAt"),
        "includes_created_edit": node.get("includesCreatedEdit") is True,
    }


def approval_comment_pages(repo, number):
    """Issue comments, 100 per page. lastEditedAt is null when the body was never edited."""
    owner, name = repo.split("/", 1)
    query = (
        "query($owner:String!,$name:String!,$number:Int!,$cursor:String){"
        "repository(owner:$owner,name:$name){pullRequest(number:$number){"
        "comments(first:100,after:$cursor){nodes{author{login} body createdAt updatedAt "
        "lastEditedAt includesCreatedEdit}pageInfo{hasNextPage endCursor}}}}}"
    )
    pages = []
    cursor = None
    for _ in range(20):
        command = ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}",
                   "-f", f"name={name}", "-F", f"number={int(number)}"]
        if cursor:
            command.extend(["-f", f"cursor={cursor}"])
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
        try:
            pull = json.loads(result.stdout)["data"]["repository"]["pullRequest"]
            connection = pull["comments"]
            nodes = connection["nodes"]
            info = connection["pageInfo"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise ValueError("approval comments") from None
        if not isinstance(nodes, list) or not isinstance(info, dict):
            raise ValueError("approval comments")
        pages.append([comment_record(node) for node in nodes])
        if not info.get("hasNextPage"):
            return pages
        cursor = info.get("endCursor")
        if not isinstance(cursor, str) or cursor == "":
            raise ValueError("approval comments")
    raise ValueError("approval comments")


def owner_approved(repo, number, head, read):
    """True when the owner has an unedited issue comment for this exact head.
    updated_at must equal created_at, and GitHub must have no edit (lastEditedAt null).
    An edited comment is not approval, including a same-second edit; post a new comment."""
    owner = repository_owner(repo, read)
    pages = read(f"repos/{repo}/issues/{number}/comments?per_page=100")
    if not isinstance(pages, list):
        raise ValueError("approval comments")
    wanted = head.lower()
    for page in pages:
        if not isinstance(page, list):
            raise ValueError("approval comments")
        for comment in page:
            if not isinstance(comment, dict):
                continue
            user = comment.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            if (same_login(login, owner) and comment_unedited(comment)
                    and approval_sha(comment.get("body")) == wanted):
                return True
    return False


def status_list(pages):
    """Newest-first status objects from GET /commits/{sha}/statuses.

    Each page is a list. The combined status object is a dict and has no creator,
    so it is not this list and must not count as success."""
    if not isinstance(pages, list):
        raise ValueError("commit statuses")
    flat = []
    for page in pages:
        if not isinstance(page, list):
            raise ValueError("commit statuses")
        for status in page:
            if not isinstance(status, dict) or "context" not in status:
                raise ValueError("commit statuses")
            flat.append(status)
    return flat


def latest_status(statuses, context):
    """The status list is newest first. The first item of a context is the one that counts."""
    for status in statuses:
        if status["context"] == context:
            return status
    return None


def prior_shas(repo, number, head, read, commit_count):
    """Earlier heads, newest first. None when history is missing or the commit list is shorter than the PR.
    GitHub returns at most 250 commits from the pulls commits API, so a short list is not a complete history."""
    found = []
    try:
        commits = [commit for page in read(f"repos/{repo}/pulls/{number}/commits?per_page=100") for commit in page]
        # A missing count, or fewer commits than the PR reports, can hide a newer failed head.
        if commit_count is None or len(commits) < commit_count:
            return None
        for commit in commits:
            sha = commit.get("sha")
            when = ((commit.get("commit") or {}).get("committer") or {}).get("date")
            if not sha or sha == head:
                continue
            if not isinstance(when, str) or when == "":
                return None
            found.append((when, sha))
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError):
        return None
    try:
        befores = read(FORCE_PUSHES + f"{repo}/{number}")
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError):
        return None
    if not isinstance(befores, list):
        return None
    for item in befores:
        if not isinstance(item, dict):
            return None
        sha = item.get("oid") or ""
        when = item.get("createdAt") or ""
        if not sha or not when:
            return None
        if sha != head:
            found.append((when, sha))
    found.sort(key=lambda pair: pair[0], reverse=True)
    ordered = []
    for _, sha in found:
        if sha not in ordered:
            ordered.append(sha)
    return ordered[:PRIOR_LIMIT]


def identity_of(repo, base, sha, read_diff, cache, read):
    if sha not in cache:
        try:
            diff = read_diff(f"repos/{repo}/compare/{base}...{sha}")
            if isinstance(diff, str) and diff.replace("\r\n", "\n").strip() == "":
                cache[sha] = "empty"
            else:
                cache[sha] = diff_identity(diff, changed_blobs(repo, sha, diff, read))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
            cache[sha] = None
    return cache[sha]


def carried_contexts(repo, number, head, base, contexts, read, read_diff, commit_count, allowed=None):
    """Contexts whose newest prior status is success and whose diff matches this head. Anything unverified stays put.
    allowed is the solo-profile creator list. None keeps the team profile and does not read the creator.
    An untrusted creator is failure, same as on the current head, so the walk does not skip it."""
    candidates = prior_shas(repo, number, head, read, commit_count)
    if not candidates:
        return set()
    cache, fetched, carried = {}, {}, set()

    def state_at(sha, context):
        if sha not in fetched:
            try:
                pages = read(f"repos/{repo}/commits/{sha}/statuses?per_page=100")
                fetched[sha] = status_list(pages)
            except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError):
                fetched[sha] = None
        # A failed lookup must not skip this SHA for an older success: its state is unknown.
        if fetched[sha] is None:
            return "unreadable"
        found = latest_status(fetched[sha], context)
        if found is None:
            return None
        return reviewed_state(found, allowed)

    for context in contexts:
        donor = None
        for sha in candidates:
            state = state_at(sha, context)
            if state is None:
                continue
            if state != "success":
                break
            current = identity_of(repo, base, head, read_diff, cache, read)
            prior = identity_of(repo, base, sha, read_diff, cache, read)
            if current is not None and current == prior:
                donor = sha
            break
        if donor:
            carried.add(context)
            print(f"review status carried {context} from {donor} onto {head}")
    return carried


# Alias, then family. Opus and Sonnet are both Claude. Two families in one name is unknown.
FAMILY_ALIASES = (
    ("composer", "composer"),
    ("gemini", "gemini"),
    ("sonnet", "claude"),
    ("opus", "claude"),
    ("claude", "claude"),
    ("grok", "grok"),
    ("gpt", "gpt"),
)
FAMILY_NAMES = "Claude, Grok, Composer, Gemini, or GPT"
COLUMN_NAMES = {
    "axis": "axis", "축": "axis", "model": "model", "모델": "model", "effort": "effort",
    "head sha": "sha", "p0": "p0", "p1": "p1", "p2": "p2", "result": "result", "결과": "result",
}
TABLE_COLUMNS = ("axis", "model", "effort", "sha", "p0", "p1", "p2")
AXIS_KEYS = {
    "standards": "standards", "spec": "spec", "security": "security",
    "버그 찾기": "bug", "bug-finding": "bug", "bug finding": "bug",
}
BODY_LIMIT = 200000


def model_family(name):
    """Family of a model name, or None when it is empty, mixed, or not in the alias table."""
    if not isinstance(name, str):
        return None
    text = name.strip().lower()
    if not text or "chatgpt" in text or re.search(r"(?<![a-z0-9])codex(?![a-z0-9])", text):
        return None
    found = set()
    for alias, family in FAMILY_ALIASES:
        if re.search(rf"(?<![a-z0-9]){alias}(?![a-z0-9])", text):
            found.add(family)
    if len(found) != 1:
        return None
    return found.pop()


def _cells(line):
    stripped = line.strip()
    if len(stripped) < 2 or not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _integer(value):
    return re.fullmatch(r"0|[1-9][0-9]*", value.strip()) is not None


def _not_applicable(model):
    text = model.strip()
    return text.startswith("해당 없음:") and text.split(":", 1)[1].strip() != ""


def evidence_table(body):
    """Rows of the last evidence table. An earlier table does not hide a later one. Parse only."""
    lines = body.split("\n")
    chosen = None
    index = 0
    while index < len(lines):
        cells = _cells(lines[index])
        mapped = [COLUMN_NAMES.get(cell.lower()) for cell in cells] if cells else []
        named = [name for name in mapped if name]
        if not cells or any(column not in named for column in TABLE_COLUMNS) or len(named) != len(set(named)):
            index += 1
            continue
        # A later header replaces any earlier table. A broken later table does not keep the old one.
        chosen = None
        rows = []
        broken = False
        index += 1
        while index < len(lines):
            row = _cells(lines[index])
            if row is None:
                break
            if _separator(row):
                index += 1
                continue
            if len(row) != len(cells):
                broken = True
                break
            rows.append({mapped[i]: row[i] for i in range(len(cells)) if mapped[i]})
            index += 1
        if not broken:
            chosen = rows
    return chosen


def evidence_problems(body, head):
    """Why the evidence table does not cover this head. Empty means it does. The body is not executed."""
    if not isinstance(body, str):
        return ["body"]
    text = body.replace("\r\n", "\n").replace("\r", "\n")[:BODY_LIMIT]
    problems = []
    record, previous, author_errors = parse_author(text)
    if any("person author" in error for error in author_errors):
        problems.append("author-model")
        families = set()
        tool = model = None
    elif record is None or any("disagree" in error or "conflicts" in error for error in author_errors):
        problems.append("author")
        families = set()
        tool = model = None
    else:
        tool, model = record
    if tool == "사람" and model == "없음":
        families = set()
    elif tool:
        families = set()
        author = model_family(model)
        if author is None:
            problems.append("unknown-family")
        else:
            families.add(author)
    for name in previous:
        family = model_family(name)
        if family is None:
            problems.append("unknown-family")
        else:
            families.add(family)
    rows = evidence_table(text)
    if rows is None:
        problems.append("table")
        return problems
    seen = {}
    for row in rows:
        key = AXIS_KEYS.get(row.get("axis", "").strip().lower())
        if key is None:
            problems.append("axis-name")
            continue
        if key in seen:
            problems.append("duplicate")
        seen[key] = row
    wanted = (head or "").lower()
    for key in ("standards", "spec", "bug", "security"):
        row = seen.get(key)
        if row is None:
            problems.append("axis-" + key)
            continue
        reviewer = row.get("model", "")
        if _not_applicable(reviewer):
            if key in ("standards", "spec"):
                problems.append("not-applicable")
            if any(row.get(column, "").strip() != "0" for column in ("p0", "p1", "p2")):
                problems.append("p0")
        elif reviewer.strip() == "" or reviewer.strip() == "미실행":
            problems.append("model")
        else:
            family = model_family(reviewer)
            if family is None:
                problems.append("unknown-family")
            elif family in families:
                problems.append("same-family")
            if not _integer(row.get("p0", "")):
                problems.append("p0")
            if not _integer(row.get("p1", "")):
                problems.append("p1")
        sha = row.get("sha", "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{40}", sha) or sha.lower() != wanted:
            problems.append("sha")
    return problems


def _dependabot_author(pull):
    user = pull.get("user") if isinstance(pull, dict) else None
    return isinstance(user, dict) and user.get("login") == DEPENDABOT


def missing(repo, number, head, base, read=read_api, read_diff=None):
    pull = read(f"repos/{repo}/pulls/{number}")
    # This pull request's base ref only. A different base is not evidence. The event base SHA
    # is then checked against the default branch, because a rerun keeps the old BASE_SHA.
    default = default_base(repo, pull, read)
    if default is None or not event_base_on_default(repo, base, default, read):
        return [BASE_REF]
    # None means a team profile: any creator still counts. A 1-person profile counts the owner
    # and STATUS_ACTORS only, and treats every other creator as failure.
    solo = not team_profile(repo, base, read)
    allowed = status_actors(repo, read) if solo else None
    # The open pull request's file and commit lists follow its current head, which can move
    # after this event. review/independent and review/security follow compare(base, head).
    patterns = COMMON_PATHS + DEPENDENCY_FILES + project_paths(repo, base, read)
    pinned, pinned_commits = pinned_change(repo, base, head, read)
    if pinned is None:
        touched = True
        bump = False
    else:
        touched = any(matches(entry.get(key, ""), patterns) for entry in pinned
                      for key in ("filename", "previous_filename"))
        bump = bool(touched and pinned_commits is not None and dependabot_bump(pull, pinned_commits, pinned))
    needed = []
    # The version-only Dependabot exception drops both reviews. A status posted anyway still has to be success.
    if not bump:
        needed.append(INDEPENDENT)
    # Compare stops at 300 files. A hidden path cannot be ruled out.
    if pinned is None or (touched and not bump):
        needed.append(SECURITY)
    statuses = status_list(read(f"repos/{repo}/commits/{head}/statuses?per_page=100"))
    # The list is newest first. An older success does not erase a newer failure.
    # An untrusted creator is failure, so it also does not reveal an older trusted success.
    newest = {}
    for status in statuses:
        context = status["context"]
        if context in newest:
            continue
        if allowed is not None and context in (INDEPENDENT, SECURITY):
            newest[context] = reviewed_state(status, allowed)
        else:
            newest[context] = status["state"]
    present = set(newest)
    for context in (INDEPENDENT, SECURITY):
        if context not in needed and context in present:
            needed.append(context)
    passed = {context for context, state in newest.items() if state == "success"}
    absent = [context for context in needed if context not in passed]
    # A failure or pending state on this head stands. Only a missing context can reuse an unchanged diff.
    reusable = [context for context in absent if context not in present]
    if not reusable:
        result = list(absent)
    else:
        carried = carried_contexts(
            repo, number, head, base, reusable, read, read_diff or read_diff_api, pull.get("commits"), allowed)
        result = [context for context in absent if context not in carried]
    # The owner comment is tied to this SHA, so an unchanged diff does not carry it. A posted status does not either.
    if pinned is None:
        needs_owner = True
        version_only = False
    else:
        introduced = touches_agents(pinned) and blob_has_team_line(repo, head, read)
        needs_owner = one_way(pinned, False) or profile_line_changes(pinned) or introduced
        version_only = (pinned_commits is not None and dependabot_bump(pull, pinned_commits, pinned)
                        and not major_change(pinned))
    if needs_owner and not version_only and solo and not owner_approved(repo, number, head, read):
        result.append(OWNER)
    # The body is the current pull request text. This run's head is the event SHA, not a later push.
    if isinstance(pull, dict) and not _dependabot_author(pull):
        found = evidence_problems(pull.get("body"), head)
        if found:
            detail = ", ".join(found)
            if "unknown-family" in found:
                detail += "; expected family " + FAMILY_NAMES
            print("review evidence: " + detail)
            result.append(EVIDENCE)
    return result


def main(env=os.environ, read=read_api, read_diff=None):
    try:
        repo, number = env["REPO"], env["PR_NUMBER"]
        head, base = env.get("HEAD_SHA") or "", env.get("BASE_SHA") or ""
        # issue_comment has no pull_request sha. Read the current head so a new push invalidates the old comment.
        if head == "" or base == "":
            pull = read(f"repos/{repo}/pulls/{number}")
            head = head or pull["head"]["sha"]
            base = base or pull["base"]["sha"]
        absent = missing(repo, number, head, base, read, read_diff)
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"review status UNVERIFIED: {error}", file=sys.stderr)
        return 2
    if absent:
        if BASE_REF in absent:
            print(f"review status FAIL on {head}: base is not the repository default branch")
        else:
            print(f"review status MISSING on {head}: " + ", ".join(absent)
                  + "; run the review, set the status on this head, then re-run this job")
        return 1
    print(f"review status PASS on {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

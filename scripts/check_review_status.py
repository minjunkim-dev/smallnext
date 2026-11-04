#!/usr/bin/env python3
"""Fail when a pull request head lacks the review statuses its changed paths need (POLICY.md §5).
Paths only: content signals stay a reviewer judgement. This shows the process ran on this exact
head; a status from the same account cannot tell a person from an agent, so it is no security boundary.
A base update creates a new head SHA. When the added and removed lines and binary blobs match a prior
success, that status covers this head. Reuse is still only a process record.
A 1-person pull request that changes a POLICY.md §10 gate path also needs the repository owner's
approval comment on this head. That comment is not reused from an older head."""

import base64
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

INDEPENDENT = "review/independent"
SECURITY = "review/security"
# Not a commit status. The job fails with this name when the owner comment is missing.
# A status posted under this name does not count: the same account can post one without the comment.
OWNER = "review/owner-approval"
DEPENDABOT = "dependabot[bot]"
WEB_FLOW = "web-flow"
TEAM_LINE = "프로필: 팀"
APPROVAL_LINE = re.compile(r"한쪽 문 승인:[ \t]*([0-9a-fA-F]{40})(?:[ \t].*)?\Z")
FORCE_PUSHES = "graphql://force-push-befores/"
PRIOR_LIMIT = 40
PROJECT_PATHS = ".github/trust-boundary-paths"
# POLICY.md §5 common paths. A pattern without "/" matches the file name at any depth.
COMMON_PATHS = (
    ".github/workflows/**", ".github/actions/**", ".github/repository-settings.json", ".github/dependabot.yml",
    ".github/dependabot.yaml", ".github/CODEOWNERS", ".github/repo-baseline.json", PROJECT_PATHS, "scripts/check_*.py",
    ".claude/settings.json", ".claude/hooks/**", ".claude/agents/**", ".claude/commands/**", ".agents/skills/**",
    ".claude/skills/**", ".mcp.json", "Dockerfile", ".env*",
)
# POLICY.md §10 gate paths. A change here needs the 1-person owner comment unless the Dependabot
# version-only exception applies. Other one-way doors (money, account, migration) are not in this list.
ONE_WAY_PATHS = (
    ".github/workflows/**", "templates/review-status.yml", "scripts/check_review_status.py",
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
    return force_push_oids(nodes)


def force_push_oids(nodes):
    """Newest-first SHAs. None when an event has no beforeCommit oid, so that head is not skipped."""
    dated = []
    for node in nodes or []:
        oid = ((node or {}).get("beforeCommit") or {}).get("oid")
        if not oid:
            return None
        dated.append((node.get("createdAt") or "", oid))
    dated.sort(reverse=True)
    return [oid for _, oid in dated]


def diff_identity(diff):
    """SHA-256 of the exact added and removed lines, file paths, modes, renames, and binary blob ids.
    Hunk positions and surrounding context do not count: a base update shifts them without changing the
    pull request. Whitespace does count. None means the diff is not safe to treat as unchanged."""
    if diff is None:
        return None
    # GitHub's diff is LF. splitlines() would also cut Unicode separators inside a line.
    text = diff.replace("\r\n", "\n").replace("\r", "\n")
    stripped = text.lstrip()
    if not stripped:
        return "empty"
    if stripped.startswith("{") or stripped.startswith("["):
        return None
    chunks = []
    current = index_line = None
    header, body = [], []
    binary = False
    in_hunk = False

    def flush():
        nonlocal current, index_line, header, body, binary
        if current is None:
            return True
        if binary and not index_line:
            return False
        if binary:
            header.append(index_line)
        chunks.append((current, tuple(header), tuple(body)))
        current = index_line = None
        header, body, binary = [], [], False
        return True

    for line in text.split("\n"):
        if line.startswith("diff --git "):
            if not flush():
                return None
            current = line
            in_hunk = False
            continue
        if current is None:
            if line.strip() == "":
                continue
            return None
        if line.startswith("index "):
            index_line = line
            continue
        if line.startswith(("new file mode ", "deleted file mode ", "old mode ", "new mode ",
                            "rename from ", "rename to ", "copy from ", "copy to ")):
            header.append(line)
            continue
        # "--- a/file" is a header. A removed line "-- note" is also "--- note", so only skip headers
        # before the first hunk.
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk and line.startswith(("--- ", "+++ ", "similarity index ", "dissimilarity index ")):
            continue
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            binary = True
            body.append(line)
            continue
        if line.startswith(("+", "-", "\\")):
            body.append(line)
            continue
        if line.startswith(" ") or line == "":
            continue
        return None
    if not flush() or not chunks:
        return None
    chunks.sort(key=lambda item: item[0])
    lines = []
    for path, kept_header, kept_body in chunks:
        lines.append(path)
        lines.extend(kept_header)
        lines.extend(kept_body)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


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


def line_majors(line, workflow):
    """Major numbers on one diff line. None means a workflow line has no # vN comment and no @vN tag."""
    body = line[1:]
    if workflow:
        found = [int(number) for number in re.findall(r"(?:#\s*v|@v)(\d+)", body, re.IGNORECASE)]
        return found or None
    found = []
    for match in re.finditer(r"(?<![\w.-])v?(\d+)(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?", body, re.IGNORECASE):
        if is_hash(match.group(0)):
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
    """Full SHA from a comment that starts with the owner approval line. None when it does not."""
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


def owner_approved(repo, number, head, read):
    """True when the repository owner has an issue comment for this exact head. Edits are the current body."""
    info = read(f"repos/{repo}")
    owner = (info.get("owner") or {}).get("login") if isinstance(info, dict) else None
    if not isinstance(owner, str) or owner == "":
        raise ValueError("repository owner")
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
            if same_login(login, owner) and approval_sha(comment.get("body")) == wanted:
                return True
    return False


def latest_state(statuses, context):
    """The combined status lists the newest state of each context first."""
    for status in statuses:
        if status["context"] == context:
            return status["state"]
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
        for commit in reversed(commits):
            sha = commit.get("sha")
            if sha and sha != head and sha not in found:
                found.append(sha)
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError):
        return None
    try:
        befores = read(FORCE_PUSHES + f"{repo}/{number}")
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError):
        return None
    if befores is None:
        return None
    for sha in befores:
        if isinstance(sha, str) and sha and sha != head and sha not in found:
            found.append(sha)
    return found[:PRIOR_LIMIT]


def identity_of(repo, base, sha, read_diff, cache):
    if sha not in cache:
        try:
            cache[sha] = diff_identity(read_diff(f"repos/{repo}/compare/{base}...{sha}"))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            cache[sha] = None
    return cache[sha]


def carried_contexts(repo, number, head, base, contexts, read, read_diff, commit_count):
    """Contexts whose newest prior status is success and whose diff matches this head. Anything unverified stays put."""
    candidates = prior_shas(repo, number, head, read, commit_count)
    if not candidates:
        return set()
    cache, fetched, carried = {}, {}, set()

    def state_at(sha, context):
        if sha not in fetched:
            try:
                pages = read(f"repos/{repo}/commits/{sha}/status?per_page=100")
                fetched[sha] = [status for page in pages for status in page["statuses"]]
            except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError):
                fetched[sha] = None
        # A failed lookup must not skip this SHA for an older success: its state is unknown.
        if fetched[sha] is None:
            return "unreadable"
        return latest_state(fetched[sha], context)

    for context in contexts:
        donor = None
        for sha in candidates:
            state = state_at(sha, context)
            if state is None:
                continue
            if state != "success":
                break
            current = identity_of(repo, base, head, read_diff, cache)
            prior = identity_of(repo, base, sha, read_diff, cache)
            if current is not None and current == prior:
                donor = sha
            break
        if donor:
            carried.add(context)
            print(f"review status carried {context} from {donor} onto {head}")
    return carried


def missing(repo, number, head, base, read=read_api, read_diff=None):
    pull = read(f"repos/{repo}/pulls/{number}")
    files = [entry for page in read(f"repos/{repo}/pulls/{number}/files?per_page=100") for entry in page]
    patterns = COMMON_PATHS + DEPENDENCY_FILES + project_paths(repo, base, read)
    touched = any(matches(entry.get(key, ""), patterns) for entry in files for key in ("filename", "previous_filename"))
    truncated = pull["changed_files"] > len(files)
    bump = False
    if not truncated and touched:
        commits = [commit for page in read(f"repos/{repo}/pulls/{number}/commits?per_page=100") for commit in page]
        # The pulls commits API returns at most 250. A short list can hide a later human commit.
        if pull.get("commits") == len(commits):
            bump = dependabot_bump(pull, commits, files)
    needed = []
    # The version-only Dependabot exception drops both reviews. A status posted anyway still has to be success.
    if not bump:
        needed.append(INDEPENDENT)
    # The files API stops listing at 3000: paths it hides cannot be ruled out.
    if truncated or (touched and not bump):
        needed.append(SECURITY)
    statuses = [status for page in read(f"repos/{repo}/commits/{head}/status?per_page=100") for status in page["statuses"]]
    present = {status["context"] for status in statuses}
    for context in (INDEPENDENT, SECURITY):
        if context not in needed and context in present:
            needed.append(context)
    passed = {status["context"] for status in statuses if status["state"] == "success"}
    absent = [context for context in needed if context not in passed]
    # A failure or pending state on this head stands. Only a missing context can reuse an unchanged diff.
    reusable = [context for context in absent if context not in present]
    if not reusable:
        result = list(absent)
    else:
        carried = carried_contexts(
            repo, number, head, base, reusable, read, read_diff or read_diff_api, pull.get("commits"))
        result = [context for context in absent if context not in carried]
    # The owner comment is tied to this SHA, so an unchanged diff does not carry it. A posted status does not either.
    # Gate paths come from compare(base, head), not the pull request's live file list.
    pinned, pinned_commits = pinned_change(repo, base, head, read)
    if pinned is None:
        needs_owner = True
        version_only = False
    else:
        introduced = touches_agents(pinned) and blob_has_team_line(repo, head, read)
        needs_owner = one_way(pinned, False) or profile_line_changes(pinned) or introduced
        version_only = (pinned_commits is not None and dependabot_bump(pull, pinned_commits, pinned)
                        and not major_change(pinned))
    if needs_owner and not version_only and not team_profile(repo, base, read) and not owner_approved(repo, number, head, read):
        result.append(OWNER)
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
        print(f"review status MISSING on {head}: " + ", ".join(absent)
              + "; run the review, set the status on this head, then re-run this job")
        return 1
    print(f"review status PASS on {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

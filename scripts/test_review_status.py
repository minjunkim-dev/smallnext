"""Which review statuses a pull request head needs, from its changed paths."""

import base64
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_review_status as tool

HEAD = "a" * 40


def git(args, **kwargs):
    """Run git without global or system config.

    commit.gpgsign and diff.noprefix in a developer config would sign the fixture
    commit or drop the a/ b/ header that git_header_path requires. Local repo config still applies."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], env=env, check=True, **kwargs)


def passing_body(head):
    lines = [
        "Author: Cursor 클라우드 에이전트 / grok-4.7", "",
        "| axis | model | effort | head SHA | P0 | P1 | P2 | result |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for axis, model in (("Standards", "Sonnet 5.5"), ("Spec", "Sonnet 5.5"),
                        ("버그 찾기", "Opus 5.5"), ("Security", "Opus 5.5")):
        lines.append(f"| {axis} | {model} | high | {head} | 0 | 0 | 0 | pass |")
    return "\n".join(lines) + "\n"


def status_rows(pairs, default_creator):
    """One page of GET /commits/{sha}/statuses. The list endpoint includes creator."""
    rows = []
    for index, item in enumerate(pairs):
        creator = default_creator
        if len(item) == 3:
            context, state, creator = item
        else:
            context, state = item
        row = {
            "avatar_url": "https://avatars.githubusercontent.com/u/1",
            "context": context,
            "created_at": f"2020-01-01T00:00:{index:02d}Z",
            "description": "",
            "id": index + 1,
            "node_id": "S",
            "state": state,
            "target_url": None,
            "updated_at": f"2020-01-01T00:00:{index:02d}Z",
            "url": "https://api.github.com/repos/o/n/statuses/1",
        }
        if creator is not None:
            row["creator"] = {"login": creator, "id": 1, "type": "User"}
        rows.append(row)
    return rows


def api(files, statuses=(), author="alice", commits=("alice",), project=None, changed=None, verified=True,
        committer=tool.WEB_FLOW, commit_shas=None, extra_status=None, force_pushes=None, commit_count=None,
        owner="owner", comments=(), agents=None, head=HEAD, compare_files=None, compare_commits=None,
        head_agents=None, force_push_times=None, body=None, number="1", base_ref="main", base_sha="BASE",
        default_branch="main", base_status="identical", status_creator=None, combined=False,
        blobs=None):
    base = {"sha": base_sha}
    if base_ref is not None:
        base["ref"] = base_ref
    pull = {"user": {"login": author}, "changed_files": len(files) if changed is None else changed,
            "head": {"sha": head}, "base": base,
            "body": passing_body(head) if body is None else body}
    commit_rows = [{
        "author": {"login": name}, "committer": {"login": committer},
        "commit": {"verification": {"verified": verified},
                   "committer": {"date": f"2020-01-{(index + 1):02d}T00:00:00Z"}},
    } for index, name in enumerate(commits)]
    repo = {"owner": {"login": owner}}
    if default_branch is not None:
        repo["default_branch"] = default_branch
    routes = {
        f"repos/o/n/pulls/{number}": pull,
        f"repos/o/n/pulls/{number}/files?per_page=100": [files],
        f"repos/o/n/pulls/{number}/commits?per_page=100": [commit_rows],
        f"repos/o/n/commits/{head}/statuses?per_page=100": (
            [{"state": "success", "statuses": status_rows(statuses, owner if status_creator is None else status_creator),
              "sha": head, "total_count": len(tuple(statuses))}]
            if combined else
            [status_rows(statuses, owner if status_creator is None else status_creator)]),
        "repos/o/n": repo,
        f"repos/o/n/issues/{number}/comments?per_page=100": [list(comments)],
    }
    if project is not None:
        routes[f"repos/o/n/contents/{tool.PROJECT_PATHS}?ref={base_sha}"] = {
            "content": base64.b64encode(project.encode()).decode()}
    if agents is not None:
        routes[f"repos/o/n/contents/AGENTS.md?ref={base_sha}"] = {
            "content": base64.b64encode(agents.encode()).decode()}
    if commit_count is not None:
        pull["commits"] = commit_count
    elif commit_shas is not None:
        pull["commits"] = len(commit_shas)
    else:
        pull["commits"] = len(list(commits))
    if commit_shas is not None:
        names = list(commits)
        commit_rows = [{
            "sha": sha, "author": {"login": names[index] if index < len(names) else author},
            "committer": {"login": committer},
            "commit": {"verification": {"verified": verified},
                       "committer": {"date": f"2020-01-{(index + 1):02d}T00:00:00Z"}},
        } for index, sha in enumerate(commit_shas)]
        routes[f"repos/o/n/pulls/{number}/commits?per_page=100"] = [commit_rows]
    pinned = list(files if compare_files is None else compare_files)
    routes[f"repos/o/n/compare/{base_sha}...{head}"] = {
        "files": pinned, "commits": commit_rows if compare_commits is None else compare_commits}
    if default_branch and base_status is not None and f"{base_sha}...{default_branch}" != f"{base_sha}...{head}":
        routes[f"repos/o/n/compare/{base_sha}...{default_branch}"] = {"status": base_status}
    if head_agents is not None:
        routes[f"repos/o/n/contents/AGENTS.md?ref={head}"] = {
            "content": base64.b64encode(head_agents.encode()).decode()}
    if extra_status:
        for sha, pairs in extra_status.items():
            routes[f"repos/o/n/commits/{sha}/statuses?per_page=100"] = [
                status_rows(pairs, owner if status_creator is None else status_creator)]
    if force_pushes is not None:
        events = []
        for index, sha in enumerate(force_pushes):
            when = (force_push_times[index] if force_push_times is not None
                    else f"2030-01-{(28 - index):02d}T00:00:00Z")
            events.append({"oid": sha, "createdAt": when})
        routes[tool.FORCE_PUSHES + f"o/n/{number}"] = events
    commits_for_blobs = {head}
    if commit_shas:
        commits_for_blobs.update(commit_shas)
    if force_pushes:
        commits_for_blobs.update(force_pushes)
    if extra_status:
        commits_for_blobs.update(extra_status)
    for commit in commits_for_blobs:
        mapping = None if blobs is None else blobs.get(commit)
        if mapping is None:
            mapping = {path: BLOB for path in default_paths(files)}
        install_blobs(routes, commit, mapping)

    def read(endpoint):
        if endpoint not in routes:
            raise subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
        return routes[endpoint]
    return read


def run(read):
    return tool.missing("o/n", "1", HEAD, "BASE", read)


def comment(body, login="owner", created_at="2020-01-01T00:00:00Z", updated_at=None, omit_times=False,
            last_edited_at=None, omit_edit=False, includes_created_edit=False):
    row = {"user": {"login": login}, "body": body}
    if not omit_times:
        row["created_at"] = created_at
        row["updated_at"] = created_at if updated_at is None else updated_at
    if not omit_edit:
        row["last_edited_at"] = last_edited_at
    if includes_created_edit:
        row["includes_created_edit"] = True
    return row


BLOB = "b" * 40
OTHER = "c" * 40


def default_paths(files):
    found = {entry.get("filename") for entry in files if entry.get("filename")}
    found.add("src/app.py")
    return found


def install_blobs(routes, commit, mapping):
    """One tree object per directory, so a nested path is more than one response."""
    root = {}
    for path, oid in mapping.items():
        if oid is None:
            continue
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = oid

    def emit(node, label):
        tree_sha = hashlib.sha256(label.encode()).hexdigest()[:40]
        entries = []
        for name in sorted(node):
            child = node[name]
            if isinstance(child, dict):
                entries.append({"path": name, "mode": "040000", "type": "tree", "sha": emit(child, label + "/" + name)})
            elif isinstance(child, tuple):
                kind, oid = child
                entries.append({"path": name, "mode": "160000" if kind == "commit" else "100644",
                                "type": kind, "sha": oid})
            else:
                entries.append({"path": name, "mode": "100644", "type": "blob", "sha": child})
        routes[f"repos/o/n/git/trees/{tree_sha}"] = {"truncated": False, "tree": entries}
        return tree_sha

    routes[f"repos/o/n/commits/{commit}"] = {"commit": {"tree": {"sha": emit(root, "tree:" + str(commit))}}}


OK = (tool.INDEPENDENT, "success")
BUMP = "@@ -1 +1 @@\n-  uses: actions/checkout@aaaaaaa # v1.0.0\n+  uses: actions/checkout@bbbbbbb # v1.1.0"
ADDED = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 def f():
     return 1
+    return 2
"""
SHIFTED = """diff --git a/src/app.py b/src/app.py
index aaaaaaa..bbbbbbb 100644
--- a/src/app.py
+++ b/src/app.py
@@ -20,3 +20,4 @@
 def f():
     return 1
+    return 2
"""
# Same added line, different function. The context lines are part of the identity.
MOVED_FROM = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,4 @@
 def format_name():
     return name
+    return True
"""
MOVED_TO = """diff --git a/src/app.py b/src/app.py
index aaaaaaa..bbbbbbb 100644
--- a/src/app.py
+++ b/src/app.py
@@ -40,3 +40,4 @@
 def is_admin():
     return name
+    return True
"""


def diffs(mapping):
    def read_diff(endpoint):
        sha = endpoint.rsplit("...", 1)[-1]
        if sha not in mapping:
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 404")
        return mapping[sha]
    return read_diff


class ReviewStatusTests(unittest.TestCase):
    def test_every_pull_request_needs_the_independent_review(self):
        files = [{"filename": "src/app.py"}]
        self.assertEqual(run(api(files)), [tool.INDEPENDENT])
        self.assertEqual(run(api(files, [OK])), [])
        self.assertEqual(run(api(files, [(tool.INDEPENDENT, "failure")])), [tool.INDEPENDENT])

    def test_a_posted_security_failure_blocks_even_when_paths_do_not_need_it(self):
        files = [{"filename": "src/app.py"}]
        self.assertEqual(run(api(files, [OK, (tool.SECURITY, "failure")])), [tool.SECURITY])
        self.assertEqual(run(api(files, [OK, (tool.SECURITY, "success")])), [])

    def test_trust_boundary_paths_also_need_security(self):
        for path in (".github/workflows/ci.yml", ".github/actions/x/action.yml", "scripts/check_review_status.py",
                     ".github/repo-baseline.json", "api/.env.local", "svc/Dockerfile", "web/package-lock.json",
                     ".claude/skills/x/SKILL.md", ".mcp.json", tool.PROJECT_PATHS):
            with self.subTest(path=path):
                owner = [tool.OWNER] if path in {".github/workflows/ci.yml", "scripts/check_review_status.py"} else []
                self.assertEqual(run(api([{"filename": path}], [OK])), [tool.SECURITY, *owner])
                self.assertEqual(run(api([{"filename": path}], [OK, (tool.SECURITY, "success")])), owner)

    def test_renaming_a_file_out_of_a_trust_boundary_path_still_counts(self):
        files = [{"filename": "docs/x.yml", "previous_filename": ".github/workflows/x.yml"}]
        self.assertEqual(run(api(files, [OK])), [tool.SECURITY, tool.OWNER])

    def test_project_paths_come_from_the_base_commit(self):
        files = [{"filename": "src/auth/login.py"}]
        self.assertEqual(run(api(files, [OK], project="# comment\nsrc/auth/**\n")), [tool.SECURITY])
        self.assertEqual(run(api(files, [OK], project="src/billing/**\n")), [])
        literal = [{"filename": "app/[id]/route.ts"}]
        for spelling in ("app/[id]/**", "app/[id]/route.ts", "/app/[id]/route.ts"):
            with self.subTest(spelling):
                self.assertEqual(run(api(literal, [OK], project=spelling + "\n")), [tool.SECURITY])
        self.assertEqual(run(api([{"filename": "x/[id].ts"}], [OK], project="[id].ts\n")), [tool.SECURITY])
        for spelling in ("/src", "src/auth", "src/auth/", "/src/auth/", "/src/auth/**"):
            with self.subTest(spelling):
                self.assertEqual(run(api(files, [OK], project=spelling + "\n")), [tool.SECURITY])

    def test_a_capped_compare_needs_security(self):
        read = api([{"filename": "src/app.py"}], [OK], compare_files=[{"filename": "src/app.py"}] * 300)
        self.assertEqual(run(read), [tool.SECURITY, tool.OWNER])

    def test_dependabot_version_bump_is_not_a_trust_boundary_change(self):
        files = [{"filename": ".github/workflows/ci.yml", "patch": BUMP},
                 {"filename": "package.json", "patch": '@@ -1 +1 @@\n-  "x": "^1.2.3",\n+  "x": "^1.3.0",'}]
        files.append({"filename": "go.sum", "patch": "@@\n-x/net v0.1.0 h1:abc+/=\n+x/net v0.2.0 h1:xyz9=\n"})
        files.append({"filename": "Cargo.lock", "patch": '@@\n-version = "1.2.3"\n-checksum = "aaaaaaa"\n'
                                                          '+version = "1.3.0"\n+checksum = "bbbbbbb"'})
        bot = tool.DEPENDABOT
        self.assertEqual(run(api(files, [OK], author=bot, commits=[bot])), [])

    def test_anything_else_in_a_dependabot_pull_request_needs_security(self):
        bot = tool.DEPENDABOT
        cases = {
            "other author": (api([{"filename": "package.json", "patch": "@@\n-1.0.0\n+1.1.0"}], [OK]),),
            "added commit": (api([{"filename": ".github/workflows/ci.yml", "patch": BUMP}], [OK],
                                 author=bot, commits=[bot, "alice"]),),
            "other line": (api([{"filename": "package.json", "patch": '@@\n-"x": "1.0.0"\n+"y": "1.0.0"'}], [OK],
                               author=bot, commits=[bot]),),
            "added line": (api([{"filename": "package.json", "patch": '@@\n+"y": "1.0.0"'}], [OK],
                               author=bot, commits=[bot]),),
            "workflow line": (api([{"filename": ".github/workflows/ci.yml", "patch": "@@\n-run: a 1\n+run: a 2"}], [OK],
                                  author=bot, commits=[bot]),),
            "amended by a person": (api([{"filename": ".github/workflows/ci.yml", "patch": BUMP}], [OK],
                                        author=bot, commits=[bot], committer="alice"),),
            "forged author": (api([{"filename": ".github/workflows/ci.yml", "patch": BUMP}], [OK],
                                  author=bot, commits=[bot], verified=False),),
            "other action": (api([{"filename": ".github/workflows/ci.yml",
                                   "patch": "@@\n-  uses: owner1/a@aaaaaaa\n+  uses: owner2/a@bbbbbbb"}], [OK],
                                 author=bot, commits=[bot]),),
            "other host": (api([{"filename": "package-lock.json",
                                 "patch": "@@\n-https://evil1.example/x-1.0.0.tgz\n+https://evil2.example/x-1.0.0.tgz"}],
                               [OK], author=bot, commits=[bot]),),
            "package name": (api([{"filename": "Cargo.lock", "patch": '@@\n-name = "pkg-2"\n+name = "pkg-3"'}], [OK],
                                 author=bot, commits=[bot]),),
            "package name like a hash": (api([{"filename": "Cargo.lock",
                                               "patch": '@@\n-name = "pkg-1234567"\n+name = "pkg-7654321"'}], [OK],
                                             author=bot, commits=[bot]),),
            "package name with underscore": (api([{"filename": "Cargo.lock", "patch": '@@\n-name = "pkg_2"\n+name = "pkg_3"'}],
                                                 [OK], author=bot, commits=[bot]),),
            "file name": (api([{"filename": "package-lock.json",
                                "patch": "@@\n-https://r/x/-/x-1.0.0.tgz\n+https://r/x/-/x-1.1.0.tgz"}], [OK],
                              author=bot, commits=[bot]),),
            "no patch": (api([{"filename": "package-lock.json"}], [OK], author=bot, commits=[bot]),),
            "other path": (api([{"filename": "Dockerfile", "patch": "@@\n-FROM a:1\n+FROM a:2"}], [OK],
                               author=bot, commits=[bot]),),
        }
        gate = {"added commit", "workflow line", "amended by a person", "forged author", "other action"}
        for name, (read,) in cases.items():
            with self.subTest(name):
                expected = [tool.SECURITY, tool.OWNER] if name in gate else [tool.SECURITY]
                self.assertEqual(run(read), expected)

    def test_dependabot_version_bump_needs_no_independent_review(self):
        bot = tool.DEPENDABOT
        files = [{"filename": ".github/workflows/ci.yml", "patch": BUMP}]
        self.assertEqual(run(api(files, author=bot, commits=[bot])), [])
        self.assertEqual(run(api(files, [(tool.INDEPENDENT, "failure")], author=bot, commits=[bot])), [tool.INDEPENDENT])
        self.assertEqual(run(api(files, [OK, (tool.SECURITY, "failure")], author=bot, commits=[bot])), [tool.SECURITY])
        # The live pull request's commit count is not this head. Compare commits are.
        short = api(files, author=bot, commits=[bot], commit_count=251)
        self.assertEqual(run(short), [])
        human = {"author": {"login": "alice"}, "committer": {"login": "alice"},
                 "commit": {"verification": {"verified": True}}}
        self.assertEqual(run(api(files, author=bot, commits=[bot], compare_commits=[human])),
                         [tool.INDEPENDENT, tool.SECURITY, tool.OWNER])
        row = {"author": {"login": bot}, "committer": {"login": tool.WEB_FLOW},
               "commit": {"verification": {"verified": True}}}
        capped = api(files, author=bot, commits=[bot], compare_commits=[row] * 250)
        self.assertEqual(run(capped), [tool.INDEPENDENT, tool.SECURITY, tool.OWNER])

    def test_a_major_action_bump_still_needs_the_owner_comment(self):
        bot = tool.DEPENDABOT
        majors = [
            "@@\n-  uses: actions/checkout@aaaaaaa # v4.2.1\n+  uses: actions/checkout@bbbbbbb # v5.0.0",
            "@@\n-  uses: actions/checkout@v4\n+  uses: actions/checkout@v5",
            "@@\n-  uses: actions/checkout@aaaaaaaa\n+  uses: actions/checkout@bbbbbbbb",
        ]
        for patch in majors:
            with self.subTest(patch=patch):
                files = [{"filename": ".github/workflows/ci.yml", "patch": patch}]
                self.assertEqual(run(api(files, author=bot, commits=[bot])), [tool.OWNER])
        minor = [{"filename": "package.json", "patch": '@@\n-  "x": "^1.2.3",\n+  "x": "^2.0.0",'}]
        self.assertEqual(run(api(minor, author=bot, commits=[bot])), [])

    def test_a_combined_status_payload_does_not_pass(self):
        combined = [{"state": "success", "statuses": [
            {"context": tool.INDEPENDENT, "state": "success", "description": "", "id": 1}]}]
        self.assertRaises(ValueError, tool.status_list, combined)
        files = [{"filename": "src/app.py"}]
        env = {"REPO": "o/n", "PR_NUMBER": "1", "HEAD_SHA": HEAD, "BASE_SHA": "BASE"}
        self.assertEqual(tool.main(env, api(files, [OK], combined=True)), 2)
        self.assertEqual(run(api(files, [OK])), [])

    def test_a_solo_profile_counts_an_owner_status_and_not_another_creator(self):
        files = [{"filename": "src/app.py"}]
        self.assertEqual(tool.STATUS_ACTORS, ())
        self.assertEqual(tool.status_actors("o/n", api(files)), ("owner",))
        self.assertEqual(run(api(files, [OK])), [])
        self.assertEqual(run(api(files, [(tool.INDEPENDENT, "success", "Owner")], owner="owner")), [])
        for creator in ("github-actions[bot]", "alice", None):
            with self.subTest(creator=creator):
                posted = [(tool.INDEPENDENT, "success", creator)]
                self.assertEqual(run(api(files, posted)), [tool.INDEPENDENT])
        # Newest untrusted success hides an older owner success. Combined status is newest first.
        hidden = [
            (tool.INDEPENDENT, "success", "github-actions[bot]"),
            (tool.INDEPENDENT, "success", "owner"),
        ]
        self.assertEqual(run(api(files, hidden)), [tool.INDEPENDENT])
        newer_owner = [
            (tool.INDEPENDENT, "success", "owner"),
            (tool.INDEPENDENT, "success", "github-actions[bot]"),
        ]
        self.assertEqual(run(api(files, newer_owner)), [])
        # The server-app setting is empty. A login in that tuple counts; a blank entry does not.
        original = tool.STATUS_ACTORS
        try:
            tool.STATUS_ACTORS = ("server-app[bot]", "")
            self.assertEqual(tool.status_actors("o/n", api(files)), ("owner", "server-app[bot]"))
            app = [(tool.INDEPENDENT, "success", "server-app[bot]")]
            self.assertEqual(run(api(files, app)), [])
            self.assertEqual(run(api(files, [(tool.INDEPENDENT, "success", "other-app[bot]")])), [tool.INDEPENDENT])
        finally:
            tool.STATUS_ACTORS = original
        team = api(files, [(tool.INDEPENDENT, "success", "github-actions[bot]")], agents="프로필: 팀\n")
        self.assertEqual(run(team), [])
        gate = [{"filename": "scripts/check_review_status.py"}]
        bot_security = [OK, (tool.SECURITY, "success", "github-actions[bot]")]
        self.assertEqual(run(api(gate, bot_security)), [tool.SECURITY, tool.OWNER])
        both = [OK, (tool.SECURITY, "success", "owner")]
        self.assertEqual(run(api(gate, both)), [tool.OWNER])

    def test_carry_does_not_reuse_another_creators_success(self):
        files = [{"filename": "src/app.py"}]
        same = diffs({"OLD": ADDED, "MID": SHIFTED, HEAD: SHIFTED})
        for creator in ("github-actions[bot]", "alice", None):
            with self.subTest(creator=creator):
                read = api(files, commit_shas=["OLD", HEAD], force_pushes=[],
                           extra_status={"OLD": [(tool.INDEPENDENT, "success", creator)]})
                self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, same), [tool.INDEPENDENT])
        owner = api(files, commit_shas=["OLD", HEAD], force_pushes=[], extra_status={"OLD": [OK]})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", owner, same), [])
        blocked = api(files, commit_shas=["OLDER", "MID", HEAD], force_pushes=[], extra_status={
            "OLDER": [OK], "MID": [(tool.INDEPENDENT, "success", "github-actions[bot]")]})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", blocked, same), [tool.INDEPENDENT])
        team = api(files, commit_shas=["OLD", HEAD], force_pushes=[], agents="프로필: 팀\n",
                   extra_status={"OLD": [(tool.INDEPENDENT, "success", "github-actions[bot]")]})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", team, same), [])

    def test_a_same_context_move_between_functions_does_not_carry(self):
        def block(name):
            return (
                f"def {name}():\n"
                "    a = 1\n    b = 2\n    c = 3\n"
                "    d = 4\n    e = 5\n    f = 6\n"
            )

        def blank(name):
            return f"def {name}():\n" + "\n" * 4 + "    marker = 0\n    tail = 1\n    tail2 = 2\n    tail3 = 3\n"

        def git_diff(before, after):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                git(["init", "-q"], cwd=root)
                git(["config", "user.email", "t@example.com"], cwd=root)
                git(["config", "user.name", "t"], cwd=root)
                (root / "app.py").write_text(before)
                git(["add", "app.py"], cwd=root)
                git(["commit", "-q", "-m", "base"], cwd=root)
                (root / "app.py").write_text(after)
                result = git(["diff"], cwd=root, capture_output=True, text=True)
                return result.stdout

        def added(source, name, needle, replacement):
            return source.replace(f"def {name}():\n{needle}", f"def {name}():\n{replacement}", 1)

        same = block("format_name") + "\n" + block("is_admin")
        needle = "    a = 1\n    b = 2\n    c = 3\n"
        planted = "    a = 1\n    b = 2\n    c = 3\n    return True\n"
        from_diff = git_diff(same, added(same, "format_name", needle, planted))
        to_diff = git_diff(same, added(same, "is_admin", needle, planted))
        self.assertIn("@@", from_diff)
        self.assertIn("def format_name():", from_diff.split("@@", 2)[-1].split("\n", 1)[0])
        self.assertIn("def is_admin():", to_diff.split("@@", 2)[-1].split("\n", 1)[0])
        self.assertNotEqual(tool.diff_identity(from_diff), tool.diff_identity(to_diff))
        # Rewriting the header to the same name matches the diff text. The post-change blob splits the files.
        renamed = to_diff.replace("def is_admin():", "def format_name():")
        self.assertEqual(tool.diff_identity(from_diff), tool.diff_identity(renamed))
        self.assertNotEqual(tool.diff_identity(from_diff, {"app.py": "a" * 40}),
                            tool.diff_identity(renamed, {"app.py": "b" * 40}))
        shifted = from_diff.replace("@@ -2,6 +2,7 @@", "@@ -40,6 +40,7 @@", 1)
        self.assertEqual(tool.diff_identity(from_diff), tool.diff_identity(shifted))

        blanks = blank("format_name") + "\n" + blank("is_admin")
        empty = "\n" * 4
        planted_blank = "\n" * 3 + "    return True\n"
        blank_from = git_diff(blanks, added(blanks, "format_name", empty, planted_blank))
        blank_to = git_diff(blanks, added(blanks, "is_admin", empty, planted_blank))
        self.assertNotEqual(tool.diff_identity(blank_from), tool.diff_identity(blank_to))

        files = [{"filename": "src/app.py"}]
        read = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[])
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": from_diff, HEAD: to_diff})),
                         [tool.INDEPENDENT])
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": blank_from, HEAD: blank_to})),
                         [tool.INDEPENDENT])

    def test_nameless_files_and_a_carriage_return_do_not_carry(self):
        def git_blob(text):
            result = git(["hash-object", "--stdin"], input=text, capture_output=True)
            return result.stdout.decode().strip()

        def git_diff(path, before, after):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                git(["init", "-q"], cwd=root)
                git(["config", "user.email", "t@example.com"], cwd=root)
                git(["config", "user.name", "t"], cwd=root)
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before)
                git(["add", path], cwd=root)
                git(["commit", "-q", "-m", "base"], cwd=root)
                target.write_bytes(after)
                result = git(["diff"], cwd=root, capture_output=True)
                return result.stdout.decode()

        def carry(path, before, left, right):
            old_diff = git_diff(path, before, left)
            new_diff = git_diff(path, before, right)
            old_blob, new_blob = git_blob(left), git_blob(right)
            self.assertNotEqual(old_blob, new_blob)
            # The function header and the context match, so the diff text alone would carry.
            self.assertEqual(tool.diff_identity(old_diff), tool.diff_identity(new_diff))
            self.assertNotEqual(tool.diff_identity(old_diff, {path: old_blob}),
                                tool.diff_identity(new_diff, {path: new_blob}))
            read = api([{"filename": path}], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]},
                       force_pushes=[], blobs={"OLD": {path: old_blob}, HEAD: {path: new_blob}})
            self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": old_diff, HEAD: new_diff})),
                             [tool.INDEPENDENT])

        def move(text, needle, insert):
            left = text.replace(needle, insert, 1)
            head, _sep, tail = text.rpartition(needle)
            return left, head + insert + tail

        yaml = """name: ci
on: push
jobs:
  one:
    runs: echo
    a: 1
    b: 2
    c: 3
    d: 4
    e: 5
    f: 6
  two:
    runs: echo
    a: 1
    b: 2
    c: 3
    d: 4
    e: 5
    f: 6
""".encode()
        carry("ci.yml", yaml, *move(yaml, b"    c: 3\n    d: 4\n", b"    c: 3\n    steps: true\n    d: 4\n"))
        payload = """{
  "a": {
    "k": 1,
    "m": 1,
    "n": 1,
    "p": 2,
    "q": 3,
    "r": 4
  },
  "b": {
    "k": 1,
    "m": 1,
    "n": 1,
    "p": 2,
    "q": 3,
    "r": 4
  }
}
""".encode()
        carry("data.json", payload, *move(payload, b'    "n": 1,\n    "p": 2,\n',
                                           b'    "n": 1,\n    "x": true,\n    "p": 2,\n'))
        source = (
            "def format_name():\n"
            "    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n    f = 6\n"
            "    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n    f = 6\n"
        ).encode()
        carry("app.py", source, *move(source, b"    c = 3\n    d = 4\n",
                                       b"    c = 3\n    return True\n    d = 4\n"))
        plain = b"def f():\n    return 1\n"
        with_lf = b"def f():\n    return 1\n    return 2\n"
        with_cr = b"def f():\n    return 1\n    return 2\r\n"
        self.assertNotEqual(git_blob(with_lf), git_blob(with_cr))
        read = api([{"filename": "app.py"}], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[],
                   blobs={"OLD": {"app.py": git_blob(with_lf)}, HEAD: {"app.py": git_blob(with_cr)}})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({
            "OLD": git_diff("app.py", plain, with_lf), HEAD: git_diff("app.py", plain, with_cr)})),
                         [tool.INDEPENDENT])
        injected = ADDED.replace("+    return 2", "+    return\r 2")
        self.assertNotEqual(tool.diff_identity(ADDED, {"src/app.py": BLOB}),
                            tool.diff_identity(injected, {"src/app.py": BLOB}))

    def test_a_deleted_rename_and_a_truncated_tree_do_not_reuse_a_bad_blob(self):
        removed = "diff --git a/src/app.py b/src/app.py\ndeleted file mode 100644\n--- a/src/app.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
        renamed = ("diff --git a/src/app.py b/src/next.py\nsimilarity index 100%\nrename from src/app.py\n"
                   "rename to src/next.py\n")
        self.assertEqual(tool.diff_identity(removed, {"src/app.py": None}),
                         tool.diff_identity(removed, {"src/app.py": None}))
        self.assertIsNone(tool.diff_identity(removed, {"src/app.py": BLOB}))
        self.assertIsNone(tool.diff_identity(renamed, {"src/next.py": "abc"}))
        planted = ADDED.replace("+    return 2", "+    return 2\n+++ /dev/null")
        self.assertIsNone(tool.diff_identity(planted, {"src/app.py": None}))
        self.assertIsNotNone(tool.diff_identity(planted, {"src/app.py": BLOB}))
        gone = api([{"filename": "src/app.py"}], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]},
                   force_pushes=[], blobs={"OLD": {"src/app.py": None}, HEAD: {"src/app.py": None}})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", gone, diffs({"OLD": removed, HEAD: removed})), [])
        moved = api([{"filename": "src/next.py"}], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]},
                    force_pushes=[], blobs={"OLD": {"src/next.py": BLOB}, HEAD: {"src/next.py": BLOB}})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", moved, diffs({"OLD": renamed, HEAD: renamed})), [])
        missing_new = api([{"filename": "src/app.py"}], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]},
                          force_pushes=[], blobs={"OLD": {"src/app.py": BLOB}, HEAD: {"src/app.py": BLOB}})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", missing_new, diffs({"OLD": renamed, HEAD: renamed})),
                         [tool.INDEPENDENT])
        nested = api([{"filename": "src/app.py"}], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]},
                     force_pushes=[])
        seen = []

        def walk(endpoint):
            seen.append(endpoint)
            return nested(endpoint)
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", walk, diffs({"OLD": ADDED, HEAD: ADDED})), [])
        self.assertGreaterEqual(sum("/git/trees/" in item for item in seen), 4)
        base = api([{"filename": "src/app.py"}], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[])

        def truncated(endpoint):
            if "/git/trees/" in endpoint:
                return {"truncated": True, "tree": []}
            return base(endpoint)
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", truncated, diffs({"OLD": ADDED, HEAD: ADDED})),
                         [tool.INDEPENDENT])

    def test_a_real_git_tree_response_is_the_blob_id(self):
        # GitHub git/trees for scripts/ at 711c827a5826fb6913a34513532495f8a089eb29. truncated is false.
        # git rev-parse of that commit's scripts/check_review_status.py is the same sha.
        commit = "711c827a5826fb6913a34513532495f8a089eb29"
        root = "0c98360ef0f4130634d19e60e81f5a682201df8f"
        scripts = "0f5f688ef34043e581aca3bf3b632bc98aaff148"
        routes = {
            f"repos/minjunkim-dev/repo-baseline/commits/{commit}": {
                "sha": commit, "commit": {"tree": {"sha": root}}},
            f"repos/minjunkim-dev/repo-baseline/git/trees/{root}": {
                "sha": root, "truncated": False, "tree": [
                    {"path": "scripts", "mode": "040000", "type": "tree", "sha": scripts}]},
            f"repos/minjunkim-dev/repo-baseline/git/trees/{scripts}": {
                "sha": scripts, "truncated": False, "tree": [
                    {"path": "check_github_settings.py", "mode": "100644", "type": "blob",
                     "sha": "58dde5aaeb1065834d78325e95579172fd697c78"},
                    {"path": "check_repo_baseline.py", "mode": "100644", "type": "blob",
                     "sha": "46f0f4e9c29d4faa3191f3108f5b6196df1564cc"},
                    {"path": "check_review_status.py", "mode": "100644", "type": "blob",
                     "sha": "6855001f4a45ae2eb22c93d4057642d7fc0f4740"},
                    {"path": "pr_author.py", "mode": "100644", "type": "blob",
                     "sha": "f4bbf1a9601d2f642a3152973c689be00401b1c9"},
                    {"path": "rerun_review_status.py", "mode": "100644", "type": "blob",
                     "sha": "2f82cff6b1667406f74e428480d334e506ff5eeb"},
                    {"path": "test_github_settings.py", "mode": "100644", "type": "blob",
                     "sha": "96f46ff30ec78ac5f7a3a5170a8a7bd654a58a6e"},
                    {"path": "test_repo_baseline.py", "mode": "100644", "type": "blob",
                     "sha": "89ea3259c58d0aa12c19f37389f6d24394a6d1c4"},
                    {"path": "test_review_status.py", "mode": "100644", "type": "blob",
                     "sha": "751db6339899e53cf681dd04e088a46ac242edc4"},
                    {"path": "test_workflow_policy.py", "mode": "100644", "type": "blob",
                     "sha": "d6c6826c89225fe0265e1825531336279c1a576e"},
                    {"path": "workflow_policy.py", "mode": "100644", "type": "blob",
                     "sha": "eb9eb5cfca0be696ea371e9114ebc9f933d2289d"}]}}

        def read(endpoint):
            if endpoint not in routes:
                raise subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
            return routes[endpoint]
        found = tool.path_oids("minjunkim-dev/repo-baseline", commit, ["scripts/check_review_status.py"], read)
        self.assertEqual(found["scripts/check_review_status.py"], "6855001f4a45ae2eb22c93d4057642d7fc0f4740")
        short = dict(routes)
        short[f"repos/minjunkim-dev/repo-baseline/git/trees/{scripts}"] = {
            "sha": scripts, "truncated": False, "tree": [
                {"path": "check_review_status.py", "mode": "100644", "type": "blob", "sha": "6855001"}]}
        self.assertRaises(ValueError, tool.path_oids, "minjunkim-dev/repo-baseline", commit,
                          ["scripts/check_review_status.py"], lambda endpoint: short[endpoint])

    def test_a_directory_named_with_b_does_not_hash_the_root_file(self):
        self.assertEqual(tool.git_header_path("diff --git a/svc b/package.json b/svc b/package.json"),
                         ("path", "svc b/package.json"))
        self.assertEqual(tool.git_header_path("diff --git a/svc/package.json b/svc/package.json"),
                         ("path", "svc/package.json"))
        self.assertEqual(tool.git_header_path("diff --git a/svc b/old.json b/svc b/new.json"), ("rename", None))
        self.assertIsNone(tool.diff_identity("diff --git a/svc b/old.json b/svc b/new.json\n"))
        renamed = ("diff --git a/svc b/old.json b/svc b/new.json\nsimilarity index 100%\n"
                   "rename from svc b/old.json\nrename to svc b/new.json\n")
        self.assertIsNotNone(tool.diff_identity(renamed, {"svc b/new.json": BLOB}))
        copied = renamed.replace("rename from", "copy from").replace("rename to", "copy to")
        self.assertIsNotNone(tool.diff_identity(copied, {"svc b/new.json": BLOB}))
        self.assertIsNone(tool.diff_identity('diff --git "a/svc b/x" "b/svc b/x"\n'))

        def git_blob(text):
            return git(["hash-object", "--stdin"], input=text, capture_output=True).stdout.decode().strip()

        def git_diff(path, before, after):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                git(["init", "-q"], cwd=root)
                git(["config", "user.email", "t@example.com"], cwd=root)
                git(["config", "user.name", "t"], cwd=root)
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before)
                git(["add", path], cwd=root)
                git(["commit", "-q", "-m", "base"], cwd=root)
                target.write_bytes(after)
                return git(["diff"], cwd=root, capture_output=True).stdout.decode()

        def move(text, needle, insert):
            left = text.replace(needle, insert, 1)
            head, _sep, tail = text.rpartition(needle)
            return left, head + insert + tail

        payload = """{
  "a": {
    "k": 1,
    "m": 1,
    "n": 1,
    "p": 2,
    "q": 3,
    "r": 4
  },
  "b": {
    "k": 1,
    "m": 1,
    "n": 1,
    "p": 2,
    "q": 3,
    "r": 4
  }
}
""".encode()
        needle = b'    "n": 1,\n    "p": 2,\n'
        insert = b'    "n": 1,\n    "x": true,\n    "p": 2,\n'
        for directory in ("svc b", "svc"):
            path = directory + "/package.json"
            before = payload
            left, right = move(before, needle, insert)
            old_diff, new_diff = git_diff(path, before, left), git_diff(path, before, right)
            self.assertIn("diff --git a/" + path + " b/" + path, old_diff)
            self.assertEqual(tool.diff_identity(old_diff), tool.diff_identity(new_diff))
            old_blob, new_blob = git_blob(left), git_blob(right)
            self.assertNotEqual(tool.diff_identity(old_diff, {path: old_blob}),
                                tool.diff_identity(new_diff, {path: new_blob}))
            # The root package.json blob is not the file that changed.
            self.assertIsNone(tool.diff_identity(old_diff, {"package.json": old_blob}))
            read = api([{"filename": path}], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[],
                       blobs={"OLD": {path: old_blob, "package.json": BLOB},
                              HEAD: {path: new_blob, "package.json": BLOB}})
            self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read,
                                          diffs({"OLD": old_diff, HEAD: new_diff})),
                             [tool.INDEPENDENT, tool.SECURITY])

    def test_an_embedded_b_slash_splits_in_the_middle_and_rfind_does_not(self):
        def old_split(line):
            rest = line[len("diff --git a/"):]
            return rest[rest.rfind(" b/") + 3:]

        same = "diff --git a/svc b/package.json b/svc b/package.json"
        root = "diff --git a/package.json b/package.json"
        self.assertEqual(old_split(same), "package.json")
        self.assertEqual(tool.git_header_path(same), ("path", "svc b/package.json"))
        self.assertNotEqual(tool.git_header_path(same)[1], old_split(same))
        self.assertEqual(tool.git_header_path(root), ("path", "package.json"))
        body = "\n@@ -1 +1 @@\n-a\n+b\n"
        full = same + body
        self.assertIsNotNone(tool.diff_identity(full, {"svc b/package.json": BLOB}))
        self.assertIsNone(tool.diff_identity(full, {"package.json": BLOB}))
        self.assertIsNotNone(tool.diff_identity(root + body, {"package.json": BLOB}))
        renamed = ("diff --git a/svc b/old.json b/svc b/new.json\n"
                   "rename from svc b/old.json\nrename to svc b/new.json\n")
        copied = renamed.replace("rename from", "copy from").replace("rename to", "copy to")
        for diff in (renamed, copied):
            self.assertIsNotNone(tool.diff_identity(diff, {"svc b/new.json": BLOB}))
            self.assertIsNone(tool.diff_identity(diff, {"new.json": BLOB}))
        self.assertIsNone(tool.diff_identity("diff --git a/svc b/old.json b/svc b/new.json\n"))
        self.assertIsNone(tool.diff_identity("diff --git a/left b/right\n@@ -1 +1 @@\n-a\n+b\n"))

    def test_tree_reads_follow_changed_paths_and_ignore_other_gitlinks(self):
        prior = "1" * 40
        current = "2" * 40
        base_sha = "3" * 40

        def tree_calls(path, siblings):
            mapping = {path: BLOB, "vendor": ("commit", "d" * 40)}
            for index in range(siblings):
                mapping[f"side{index}/file.txt"] = BLOB
            base = api([{"filename": path}], head=current, base_sha=base_sha, commit_shas=[prior, current],
                       extra_status={prior: [OK]}, force_pushes=[],
                       blobs={prior: mapping, current: mapping})
            seen = []

            def read(endpoint):
                seen.append(endpoint)
                return base(endpoint)
            diff = ADDED.replace("src/app.py", path)
            self.assertEqual(tool.missing("o/n", "1", current, base_sha, read, diffs({prior: diff, current: diff})), [])
            self.assertIn(f"repos/o/n/commits/{prior}", seen)
            self.assertIn(f"repos/o/n/commits/{current}", seen)
            self.assertFalse(any(endpoint.endswith("/commits/HEAD") or endpoint.endswith("/commits/OLD") for endpoint in seen))
            trees = sum("/git/trees/" in item for item in seen)
            root_sha = read(f"repos/o/n/commits/{current}")["commit"]["tree"]["sha"]
            listing = {item["path"]: item for item in read(f"repos/o/n/git/trees/{root_sha}")["tree"]}
            self.assertEqual(listing["vendor"]["type"], "commit")
            self.assertEqual(tool.path_oids("o/n", current, [path], read)[path], BLOB)
            if siblings:
                self.assertIn("side0", listing)
                self.assertFalse(any(listing["side0"]["sha"] in endpoint for endpoint in seen))
            return trees

        self.assertEqual(tree_calls("pkg.json", 30), tree_calls("pkg.json", 0))
        self.assertEqual(tree_calls("pkg.json", 30), 2)
        deep = tree_calls("a/b/c/d.txt", 30)
        self.assertEqual(deep, tree_calls("a/b/c/d.txt", 0))
        self.assertEqual(deep, 8)
        self.assertEqual(deep // 2, len("a/b/c/d.txt".split("/")))
        link = ("diff --git a/vendor b/vendor\nindex 1111111..2222222 160000\n--- a/vendor\n+++ b/vendor\n"
                "@@ -1 +1 @@\n-Subproject commit " + ("a" * 40) + "\n+Subproject commit " + ("a" * 40) + "\n")
        held = "e" * 40
        other = "d" * 40
        same = api([{"filename": "vendor"}], head=current, base_sha=base_sha, commit_shas=[prior, current],
                   extra_status={prior: [OK]}, force_pushes=[],
                   blobs={prior: {"vendor": ("commit", held), "other": ("commit", other)},
                          current: {"vendor": ("commit", held), "other": ("commit", other)}})
        self.assertEqual(tool.missing("o/n", "1", current, base_sha, same, diffs({prior: link, current: link})), [])
        self.assertEqual(tool.path_oids("o/n", current, ["vendor"], same)["vendor"], held)
        self.assertNotEqual(tool.diff_identity(link, {"vendor": held}),
                            tool.diff_identity(link, {"vendor": "f" * 40}))
        moved = api([{"filename": "vendor"}], head=current, base_sha=base_sha, commit_shas=[prior, current],
                    extra_status={prior: [OK]}, force_pushes=[],
                    blobs={prior: {"vendor": ("commit", held), "other": ("commit", other)},
                           current: {"vendor": ("commit", "f" * 40), "other": ("commit", other)}})
        self.assertEqual(tool.missing("o/n", "1", current, base_sha, moved, diffs({prior: link, current: link})),
                         [tool.INDEPENDENT])
        self.assertEqual(tool.path_oids("o/n", current, ["vendor"], moved)["vendor"], "f" * 40)

    def test_moving_a_line_into_another_function_does_not_carry(self):
        files = [{"filename": "src/app.py"}]
        read = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[])
        moved = diffs({"OLD": MOVED_FROM, HEAD: MOVED_TO})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, moved), [tool.INDEPENDENT])
        shifted = diffs({"OLD": ADDED, HEAD: SHIFTED})
        moved_lines = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[],
                          blobs={"OLD": {"src/app.py": BLOB}, HEAD: {"src/app.py": OTHER}})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", moved_lines, shifted), [tool.INDEPENDENT])
        touched = SHIFTED.replace("    return 1", "    return 0", 1)
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": ADDED, HEAD: touched})),
                         [tool.INDEPENDENT])

    def test_an_unchanged_diff_reuses_the_prior_success(self):
        files = [{"filename": "src/app.py"}]
        read = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[])
        same = diffs({"OLD": ADDED, HEAD: ADDED})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, same), [])
        shifted = diffs({"OLD": ADDED, HEAD: SHIFTED})
        moved_lines = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[],
                          blobs={"OLD": {"src/app.py": BLOB}, HEAD: {"src/app.py": OTHER}})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", moved_lines, shifted), [tool.INDEPENDENT])
        indent = SHIFTED.replace("+    return 2", "+        return 2")
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": ADDED, HEAD: indent})),
                         [tool.INDEPENDENT])

    def test_a_failure_on_this_head_is_not_replaced_by_an_older_success(self):
        files = [{"filename": "src/app.py"}]
        read = api(files, [(tool.INDEPENDENT, "failure")], commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": ADDED, HEAD: SHIFTED})),
                         [tool.INDEPENDENT])

    def test_a_newer_failed_status_blocks_an_older_match(self):
        files = [{"filename": "src/app.py"}]
        base = api(files, commit_shas=["OLDER", "MID", HEAD], extra_status={
            "OLDER": [OK], "MID": [(tool.INDEPENDENT, "failure")]}, force_pushes=[])
        seen = []

        def read(endpoint):
            seen.append(endpoint)
            return base(endpoint)
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read,
                                      diffs({"OLDER": ADDED, "MID": SHIFTED, HEAD: SHIFTED})),
                         [tool.INDEPENDENT])
        self.assertIn("repos/o/n/commits/MID/statuses?per_page=100", seen)

    def test_a_rebase_parent_can_carry_the_status(self):
        files = [{"filename": "src/app.py"}]
        read = api(files, commit_shas=[HEAD], force_pushes=["OLD"], extra_status={"OLD": [OK]})
        # The same blob means this file's bytes did not change. A line-number shift still carries.
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": ADDED, HEAD: SHIFTED})), [])
        changed = api(files, commit_shas=[HEAD], force_pushes=["OLD"], extra_status={"OLD": [OK]},
                      blobs={"OLD": {"src/app.py": BLOB}, HEAD: {"src/app.py": OTHER}})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", changed, diffs({"OLD": ADDED, HEAD: SHIFTED})),
                         [tool.INDEPENDENT])

    def test_security_reuses_the_same_diff_and_does_not_borrow_a_different_context(self):
        files = [{"filename": ".github/workflows/ci.yml", "patch": "@@\n-run: a\n+run: b"}]
        both = {"OLD": [OK, (tool.SECURITY, "success")]}
        read = api(files, commit_shas=["OLD", HEAD], extra_status=both, force_pushes=[])
        same = diffs({"OLD": ADDED, HEAD: SHIFTED})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, same), [tool.OWNER])
        only_independent = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[])
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", only_independent, same), [tool.SECURITY, tool.OWNER])

    def test_an_unreadable_newer_status_does_not_fall_through(self):
        files = [{"filename": "src/app.py"}]
        base = api(files, commit_shas=["OLDER", "MID", HEAD], extra_status={"OLDER": [OK]}, force_pushes=[])
        seen = []

        def read(endpoint):
            seen.append(endpoint)
            return base(endpoint)
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLDER": ADDED, HEAD: SHIFTED})),
                         [tool.INDEPENDENT])
        self.assertIn("repos/o/n/commits/MID/statuses?per_page=100", seen)

    def test_a_short_commit_list_does_not_carry(self):
        files = [{"filename": "src/app.py"}]
        read = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[], commit_count=251)
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": ADDED, HEAD: SHIFTED})),
                         [tool.INDEPENDENT])

    def test_a_force_push_without_a_before_sha_is_incomplete_history(self):
        self.assertIsNone(tool.force_push_oids([{"beforeCommit": None, "createdAt": "t"}]))
        self.assertIsNone(tool.force_push_oids([None]))
        self.assertEqual(tool.force_push_oids([]), [])
        self.assertEqual(tool.force_push_oids([
            {"createdAt": "a", "beforeCommit": {"oid": "A"}},
            {"createdAt": "b", "beforeCommit": {"oid": "B"}},
        ]), ["B", "A"])

    def test_an_unreadable_history_does_not_carry(self):
        files = [{"filename": "src/app.py"}]
        same = diffs({"OLD": ADDED, HEAD: SHIFTED})
        hidden_timeline = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", hidden_timeline, same), [tool.INDEPENDENT])
        listed = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[])

        def unreadable_timeline(endpoint):
            if endpoint.startswith(tool.FORCE_PUSHES):
                return None
            return listed(endpoint)
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", unreadable_timeline, same), [tool.INDEPENDENT])
        only_rebase = api(files, force_pushes=["OLD"], extra_status={"OLD": [OK]})

        def unreadable_commits(endpoint):
            if endpoint.endswith("/commits?per_page=100"):
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 500")
            return only_rebase(endpoint)
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", unreadable_commits, same), [tool.INDEPENDENT])

    def test_an_unreadable_diff_does_not_reuse_a_status(self):
        files = [{"filename": "src/app.py"}]
        base = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[])
        seen = []

        def read(endpoint):
            seen.append(endpoint)
            return base(endpoint)

        def boom(endpoint):
            seen.append(endpoint)
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 406")
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, boom), [tool.INDEPENDENT])
        self.assertTrue(any(item.startswith("repos/o/n/compare/") for item in seen))
        env = {"REPO": "o/n", "PR_NUMBER": "1", "HEAD_SHA": HEAD, "BASE_SHA": "BASE"}
        self.assertEqual(tool.main(env, read, boom), 1)

    def test_diff_identity_ignores_position_and_keeps_whitespace_and_binary_blobs(self):
        self.assertEqual(tool.diff_identity(ADDED), tool.diff_identity(SHIFTED))
        self.assertEqual(tool.diff_identity(ADDED, {"src/app.py": BLOB}),
                         tool.diff_identity(SHIFTED, {"src/app.py": BLOB}))
        self.assertNotEqual(tool.diff_identity(ADDED, {"src/app.py": BLOB}),
                            tool.diff_identity(SHIFTED, {"src/app.py": OTHER}))
        self.assertNotEqual(tool.diff_identity(MOVED_FROM), tool.diff_identity(MOVED_TO))
        touched = SHIFTED.replace("    return 1", "    return 0", 1)
        self.assertNotEqual(tool.diff_identity(ADDED), tool.diff_identity(touched))
        self.assertNotEqual(tool.diff_identity(ADDED), tool.diff_identity(SHIFTED.replace("+    return 2", "+        return 2")))
        self.assertEqual(tool.diff_identity(""), "empty")
        self.assertIsNone(tool.diff_identity('{"message":"diff too large"}'))
        self.assertIsNone(tool.diff_identity("diff --git a/a b/a\nnot a diff line\n"))
        binary = "diff --git a/a.bin b/a.bin\nindex 1111111..2222222 100644\nBinary files a/a.bin and b/a.bin differ\n"
        other = binary.replace("1111111..2222222", "1111111..3333333")
        self.assertEqual(tool.diff_identity(binary), tool.diff_identity(other))
        self.assertIsNotNone(tool.diff_identity(binary.replace("index 1111111..2222222 100644\n", "")))
        self.assertIsNone(tool.diff_identity(binary, {"a.bin": "1111111"}))
        self.assertNotEqual(tool.diff_identity(binary, {"a.bin": "a" * 40}),
                            tool.diff_identity(other, {"a.bin": "b" * 40}))
        swapped = SHIFTED + ADDED.replace("src/app.py", "src/b.py")
        reverse = ADDED.replace("src/app.py", "src/b.py") + SHIFTED
        self.assertEqual(tool.diff_identity(swapped), tool.diff_identity(reverse))
        removed = ("diff --git a/a.sql b/a.sql\nindex 1111111..2222222 100644\n--- a/a.sql\n+++ b/a.sql\n"
                   "@@ -1 +1 @@\n--- note\n+-- note 2\n")
        self.assertNotEqual(tool.diff_identity(removed), tool.diff_identity(removed.replace("+-- note 2", "+-- note 3")))
        self.assertEqual(tool.diff_identity(removed), tool.diff_identity(removed.replace("--- a/a.sql", "--- a/other")))
        plus = ("diff --git a/a.hs b/a.hs\nindex 1111111..2222222 100644\n--- a/a.hs\n+++ b/a.hs\n"
                "@@ -1 +1 @@\n-x\n+++ x\n")
        self.assertNotEqual(tool.diff_identity(plus), tool.diff_identity(plus.replace("+++ x", "+++ y")))
        one_line = "diff --git a/a b/a\n@@ -1 +1 @@\n+a\u2028+b\n"
        two_lines = "diff --git a/a b/a\n@@ -1 +1 @@\n+a\n+b\n"
        self.assertNotEqual(tool.diff_identity(one_line), tool.diff_identity(two_lines))
        self.assertIsNotNone(tool.diff_identity("diff --git a/a b/a\n@@ -1 +1 @@\n \x0c\n+x\n"))

    def test_comment_edit_fields_come_from_graphql(self):
        self.assertIsNone(tool.comment_list_target("repos/o/n"))
        self.assertEqual(tool.comment_list_target("repos/o/n/issues/12/comments?per_page=100"), ("o/n", "12"))
        node = {"author": {"login": "Owner"}, "body": "x", "createdAt": "t", "updatedAt": "t",
                "lastEditedAt": None, "includesCreatedEdit": False}
        self.assertEqual(tool.comment_record(node)["last_edited_at"], None)
        self.assertFalse(tool.comment_record(node)["includes_created_edit"])
        edited = dict(node, lastEditedAt="t", includesCreatedEdit=True)
        self.assertEqual(tool.comment_record(edited)["last_edited_at"], "t")
        self.assertTrue(tool.comment_record(edited)["includes_created_edit"])
        for broken in ({}, {"lastEditedAt": None}, {"includesCreatedEdit": False}):
            with self.assertRaises(ValueError):
                tool.comment_record(broken)

    def test_owner_comment_matches_only_this_head(self):
        head = "a" * 40
        other = "b" * 40
        files = [{"filename": "templates/review-status.yml"}]
        reviews = [OK, (tool.SECURITY, "success")]

        def check(comments, expected, **kwargs):
            read = api(files, reviews, comments=comments, head=head, **kwargs)
            self.assertEqual(tool.missing("o/n", "1", head, "BASE", read), expected)

        fresh = "2020-01-01T00:00:00Z"
        check([comment(f"한쪽 문 승인: {head} 메모", login="Owner")], [], owner="owner")
        check([comment(f"되돌리기 어려움 승인: {head}", created_at=fresh, updated_at=fresh)], [])
        check([comment(f"한쪽 문 승인: {head}", created_at=fresh, updated_at=fresh)], [])
        check([comment(f"되돌리기 어려움 승인: {head}", updated_at="2020-01-02T00:00:00Z")], [tool.OWNER])
        check([comment(f"되돌리기 어려움 승인: {head}", last_edited_at=fresh)], [tool.OWNER])
        check([comment(f"한쪽 문 승인: {head}", includes_created_edit=True)], [tool.OWNER])
        check([comment(f"되돌리기 어려움 승인: {head}", omit_edit=True)], [tool.OWNER])
        check([comment(f"한쪽 문 승인: {head}", updated_at="2020-01-01T00:00:00+00:00")], [tool.OWNER])
        check([comment(f"되돌리기 어려움 승인: {head}", omit_times=True)], [tool.OWNER])
        check([
            comment(f"되돌리기 어려움 승인: {head}", updated_at="2020-01-02T00:00:00Z"),
            comment(f"한쪽 문 승인: {head}"),
        ], [])
        check([comment(f"한쪽 문 승인: {head}\r\n메모")], [])
        check([comment(f"한쪽 문 승인: {other}")], [tool.OWNER])
        check([comment(f"되돌리기 어려움 승인: {head}")], [])
        check([comment(f"되돌리기 어려움 승인: {head} 메모")], [])
        check([comment(f"되돌리기 어려움 승인: {head}\r\n메모")], [])
        check([comment(f"되돌리기 어려움 승인: {other}")], [tool.OWNER])
        check([
            comment(f"되돌리기 어려움 승인: {other}"),
            comment(f"한쪽 문 승인: {other}"),
        ], [tool.OWNER])
        check([
            comment(f"되돌리기 어려움 승인: {other}"),
            comment(f"한쪽 문 승인: {head}"),
        ], [])
        check([
            comment(f"되돌리기 어려움 승인: {head}"),
            comment(f"한쪽 문 승인: {other}"),
        ], [])
        check([comment(f"되돌리기어려움 승인: {head}")], [tool.OWNER])
        check([comment(f"되돌리기 어려움승인: {head}")], [tool.OWNER])
        check([comment(f"되돌리기 쉬움 승인: {head}")], [tool.OWNER])
        check([comment(f" 되돌리기 어려움 승인: {head}")], [tool.OWNER])
        check([comment(f"참고\n되돌리기 어려움 승인: {head}")], [tool.OWNER])
        check([comment(f"한쪽 문승인: {head}")], [tool.OWNER])
        check([comment(f"한쪽 문 승인: {head}", login="alice")], [tool.OWNER])
        check([comment(f"한쪽 문 승인: {head}", login="minjun")], [tool.OWNER], owner="acme-org")
        check([], [tool.OWNER])
        check([comment(f"참고\n한쪽 문 승인: {head}")], [tool.OWNER])
        check([comment("한쪽 문 승인: " + "a" * 39)], [tool.OWNER])
        check([], [tool.OWNER], agents="설명 프로필: 팀\n")
        check([], [], agents="프로필: 팀\n")
        posted = api(files, reviews + [(tool.OWNER, "success")], head=head)
        self.assertEqual(tool.missing("o/n", "1", head, "BASE", posted), [tool.OWNER])
        self.assertEqual(run(api([{"filename": "src/app.py"}], [OK])), [])
        bot = tool.DEPENDABOT
        bump = [{"filename": ".github/workflows/ci.yml", "patch": BUMP}]
        self.assertEqual(run(api(bump, author=bot, commits=[bot])), [])
        self.assertEqual(run(api([{"filename": "scripts/check_repo_baseline.py"}], [OK, (tool.SECURITY, "success")])), [])
        self.assertEqual(run(api([{"filename": "AGENTS.md", "patch": "@@\n+프로필: 팀\n"}], [OK])), [tool.OWNER])
        self.assertEqual(run(api([{"filename": "AGENTS.md", "patch": "@@\n+다른 줄\n"}], [OK])), [])
        self.assertEqual(run(api([{"filename": "AGENTS.md"}], [OK])), [tool.OWNER])
        self.assertEqual(run(api([{"filename": "AGENTS.md", "patch": "@@\n-프로필: 팀\n"}], [OK], agents="프로필: 팀\n")), [])
        renamed = [{"filename": "AGENTS.md", "previous_filename": "notes.md", "patch": "@@\n 프로필 안내\n+다른 줄\n"}]
        self.assertEqual(run(api(renamed, [OK], head_agents="프로필: 팀\n")), [tool.OWNER])

    def test_owner_approval_uses_the_compare_for_this_head(self):
        head = "d" * 40
        reviews = [OK, (tool.SECURITY, "success")]
        swapped = api([{"filename": "src/app.py"}], reviews, head=head,
                      compare_files=[{"filename": ".github/workflows/ci.yml"}])
        self.assertEqual(tool.missing("o/n", "1", head, "BASE", swapped), [tool.OWNER])
        current = api([{"filename": ".github/workflows/ci.yml"}], reviews, head=head,
                      compare_files=[{"filename": "src/app.py"}])
        self.assertEqual(tool.missing("o/n", "1", head, "BASE", current), [])
        huge = api([{"filename": "src/app.py"}], [OK], compare_files=[{"filename": "src/app.py"}] * 300)
        self.assertEqual(run(huge), [tool.SECURITY, tool.OWNER])
        base = api([{"filename": "src/app.py"}], [OK])

        def too_big(endpoint):
            # The ancestry compare must stay readable. Only the pull-request diff is too large.
            if "/compare/" in endpoint and not endpoint.endswith("...main"):
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 406")
            return base(endpoint)
        self.assertEqual(run(too_big), [tool.SECURITY, tool.OWNER])

    def test_a_new_head_invalidates_the_owner_comment(self):
        files = [{"filename": "scripts/check_review_status.py"}]
        old = "b" * 40
        read = api(files, commit_shas=[old, HEAD], extra_status={old: [OK, (tool.SECURITY, "success")]},
                   force_pushes=[], comments=[comment(f"한쪽 문 승인: {old}")])
        same = diffs({old: ADDED, HEAD: SHIFTED})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, same), [tool.OWNER])
        read_new = api(files, commit_shas=[old, HEAD], extra_status={old: [OK, (tool.SECURITY, "success")]},
                       force_pushes=[], comments=[comment(f"되돌리기 어려움 승인: {old}")])
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read_new, same), [tool.OWNER])
        matched = "c" * 40
        passed = api(files, [OK, (tool.SECURITY, "success")], comments=[comment(f"한쪽 문 승인: {matched}")], head=matched)
        self.assertEqual(tool.missing("o/n", "1", matched, "BASE", passed), [])

    def test_unreadable_approval_comments_do_not_pass(self):
        files = [{"filename": "templates/review-status-policy.json"}]
        base = api(files, [OK, (tool.SECURITY, "success")])

        def read(endpoint):
            if endpoint.endswith("/comments?per_page=100"):
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 500")
            return base(endpoint)
        env = {"REPO": "o/n", "PR_NUMBER": "1", "HEAD_SHA": HEAD, "BASE_SHA": "BASE"}
        self.assertEqual(tool.main(env, read), 2)

        def broken_profile(endpoint):
            if endpoint.endswith("/contents/AGENTS.md?ref=BASE"):
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 500")
            return base(endpoint)
        self.assertEqual(tool.main(env, broken_profile), 2)

    def test_a_comment_event_without_shas_reads_the_pull_request(self):
        env = {"REPO": "o/n", "PR_NUMBER": "1"}
        self.assertEqual(tool.main(env, api([{"filename": "src/app.py"}], [OK])), 0)

    def test_review_requirements_follow_this_head_not_the_live_pull_request(self):
        head = "e" * 40
        live_docs = api([{"filename": "src/app.py"}], [OK], head=head,
                        compare_files=[{"filename": ".github/workflows/ci.yml"}])
        self.assertEqual(tool.missing("o/n", "1", head, "BASE", live_docs), [tool.SECURITY, tool.OWNER])
        live_workflow = api([{"filename": ".github/workflows/ci.yml"}], [OK], head=head,
                            compare_files=[{"filename": "src/app.py"}])
        self.assertEqual(tool.missing("o/n", "1", head, "BASE", live_workflow), [])

    def test_a_newer_force_push_failure_blocks_an_older_success(self):
        files = [{"filename": "src/app.py"}]
        read = api(files, commit_shas=["OLDER", HEAD], extra_status={
            "OLDER": [OK], "FAILED": [(tool.INDEPENDENT, "failure")]}, force_pushes=["FAILED"])
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLDER": ADDED, HEAD: SHIFTED})),
                         [tool.INDEPENDENT])
        older_failure = api(files, commit_shas=["MID", HEAD], extra_status={
            "MID": [OK], "ANCIENT": [(tool.INDEPENDENT, "failure")]}, force_pushes=["ANCIENT"],
            force_push_times=["2019-01-01T00:00:00Z"])
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", older_failure,
                                      diffs({"MID": ADDED, HEAD: SHIFTED})), [])

    def test_a_newer_failure_on_this_head_hides_an_older_success(self):
        files = [{"filename": "src/app.py"}]
        self.assertEqual(run(api(files, [(tool.INDEPENDENT, "failure"), OK])), [tool.INDEPENDENT])

    def test_a_template_pin_without_a_version_marker_is_an_unknown_major(self):
        same_digit = ("@@\n-  uses: actions/checkout@3" + "a" * 39
                      + "\n+  uses: actions/checkout@3" + "b" * 39)
        self.assertTrue(tool.major_change([{"filename": "templates/review-status.yml", "patch": same_digit}]))
        self.assertEqual(tool.line_majors("-checksum \"7aaaaaa\"", False), [])
        commented = ("@@\n-  uses: actions/checkout@3" + "a" * 39 + " # v7.0.1"
                     + "\n+  uses: actions/checkout@4" + "b" * 39 + " # v7.0.1")
        self.assertFalse(tool.major_change([{"filename": "templates/review-status.yml", "patch": commented}]))

    def test_review_evidence_table_matches_this_head_and_not_the_author_model(self):
        head = HEAD
        other = "c" * 40
        files = [{"filename": "src/app.py"}]
        self.assertEqual(run(api(files, [OK])), [])
        self.assertEqual(run(api(files, [OK], body="")), [tool.EVIDENCE])
        self.assertEqual(run(api(files, [OK], body="", author=tool.DEPENDABOT)), [])
        shell = "Author: Cursor / grok-4.7\n$(touch /tmp/review-evidence-executed)\n"
        self.assertIn("table", tool.evidence_problems(shell, head))
        self.assertFalse(Path("/tmp/review-evidence-executed").exists())

        def table(model, sha, p0="0", p1="0", axis="Standards"):
            return "\n".join([
                "Author: Cursor / grok-4.7",
                "| axis | model | effort | head SHA | P0 | P1 | P2 | result |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
                f"| {axis} | {model} | high | {sha} | {p0} | {p1} | note | pass |",
                f"| Spec | Sonnet 5.5 | high | {sha} | 0 | 0 | 0 | pass |",
                f"| 버그 찾기 | Opus 5.5 | high | {sha} | 0 | 0 | 0 | pass |",
                f"| Security | Opus 5.5 | high | {sha} | 0 | 0 | 0 | pass |",
                "",
            ])

        self.assertEqual(tool.evidence_problems(table("Sonnet 5.5", head), head), [])
        self.assertIn("sha", tool.evidence_problems(table("Sonnet 5.5", other), head))
        self.assertIn("sha", tool.evidence_problems(table("Sonnet 5.5", "HEAD"), head))
        self.assertIn("same-family", tool.evidence_problems(table("Opus 5.5", head).replace(
            "Author: Cursor / grok-4.7", "Author: Claude Code / claude-opus-5.5"), head))
        self.assertIn("same-family", tool.evidence_problems(table("Sonnet 5.5", head).replace(
            "Author: Cursor / grok-4.7", "Author: Claude Code / Opus 5.5"), head))
        self.assertIn("same-family", tool.evidence_problems(table("cursor-grok-4.6", head), head))
        self.assertEqual([], tool.evidence_problems(table("Composer 2.5", head), head))
        stale = table("Sonnet 5.5", other) + "\n" + table("Composer 2.5", head)
        self.assertEqual([], tool.evidence_problems(stale, head))
        self.assertIn("sha", tool.evidence_problems(table("Composer 2.5", head) + "\n" + table("Sonnet 5.5", other), head))
        broken = table("Sonnet 5.5", head) + "\n| axis | model | effort | head SHA | P0 | P1 | P2 | result |\n| Standards | Sonnet 5.5 | high | " + head + " | 0 |\n"
        self.assertIn("table", tool.evidence_problems(broken, head))
        hidden = "Author: Cursor / grok-4.7\nAuthor: Claude Code / Opus 5.5\n" + table("Sonnet 5.5", head)
        self.assertIn("author", tool.evidence_problems(hidden, head))
        self.assertIn("unknown-family", tool.evidence_problems(table("mystery-model", head), head))
        self.assertIn("author-model", tool.evidence_problems(table("Sonnet 5.5", head).replace(
            "Author: Cursor / grok-4.7", "Author: 사람 / grok-4.7"), head))
        self.assertEqual("claude", tool.model_family("Opus 5.5"))
        self.assertEqual("claude", tool.model_family("claude-opus-5-5-high"))
        self.assertEqual("claude", tool.model_family("Sonnet 5.5"))
        self.assertEqual("grok", tool.model_family("grok-4.7-high-fast"))
        self.assertEqual("composer", tool.model_family("Composer 2.5"))
        self.assertEqual("gemini", tool.model_family("Gemini 4"))
        self.assertEqual("gpt", tool.model_family("GPT-5.6"))
        self.assertIsNone(tool.model_family("grok-composer"))
        self.assertIsNone(tool.model_family("chatgpt"))
        self.assertIsNone(tool.model_family("codex"))
        self.assertIsNone(tool.model_family("not-a-model"))
        self.assertIn("p0", tool.evidence_problems(table("Sonnet 5.5", head, p0="no"), head))
        self.assertIn("p1", tool.evidence_problems(table("Sonnet 5.5", head, p1=""), head))
        self.assertIn("model", tool.evidence_problems(table("미실행", head), head))
        skipped = table("Sonnet 5.5", head).replace(
            "| 버그 찾기 | Opus 5.5 |", "| 버그 찾기 | 해당 없음: 코드 diff 없음 |")
        self.assertEqual(tool.evidence_problems(skipped, head), [])
        bad_p2 = skipped.replace(
            f"| 버그 찾기 | 해당 없음: 코드 diff 없음 | high | {head} | 0 | 0 | 0 |",
            f"| 버그 찾기 | 해당 없음: 코드 diff 없음 | high | {head} | 0 | 0 | 1 |")
        self.assertIn("p0", tool.evidence_problems(bad_p2, head))
        self.assertIn("not-applicable", tool.evidence_problems(table("해당 없음: 문서", head), head))
        korean = "\n".join([
            "작성 도구: Cursor",
            "작성 모델: grok-4.7",
            "| 축 | 모델 | effort | head SHA | P0 | P1 | P2 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            f"| Standards | Sonnet 5.5 | high | {head} | 0 | 0 | 0 |",
            f"| Spec | Sonnet 5.5 | high | {head} | 0 | 0 | 0 |",
            f"| 버그 찾기 | Opus 5.5 | high | {head} | 0 | 0 | 0 |",
            f"| Security | 해당 없음: 신뢰 경계 변경 아님 | 해당 없음 | {head} | 0 | 0 | 0 |",
            "",
        ])
        self.assertEqual(tool.evidence_problems(korean, head), [])
        self.assertIn("unknown-family", tool.evidence_problems(
            table("Sonnet 5.5", head) + "이전 작성 모델: not-a-model\n", head))
        self.assertIn("same-family", tool.evidence_problems(
            table("Sonnet 5.5", head).replace("Author: Cursor / grok-4.7",
                                              "작성 도구: Cursor\n작성 모델: grok-4.7\n이전 작성 모델: Sonnet 5.5"), head))

    def test_a_side_base_fails_and_a_main_base_still_passes(self):
        files = [{"filename": "src/app.py"}]
        output = StringIO()
        with redirect_stdout(output):
            side = run(api(files, [OK], base_ref="feature"))
        self.assertEqual(side, [tool.BASE_REF])
        text = output.getvalue()
        self.assertIn("base feature is not the default branch main", text)
        self.assertEqual(run(api(files, [OK], base_ref="main")), [])
        env = {"REPO": "o/n", "PR_NUMBER": "1", "HEAD_SHA": HEAD, "BASE_SHA": "BASE"}
        cli = StringIO()
        with redirect_stdout(cli):
            code = tool.main(env, api(files, [OK], base_ref="feature"))
        self.assertEqual(code, 1)
        self.assertIn("review status FAIL", cli.getvalue())
        self.assertIn("base is not the repository default branch", cli.getvalue())
        for kwargs in ({"base_ref": None}, {"default_branch": None}, {"base_ref": ""}, {"default_branch": ""}):
            with self.subTest(**kwargs):
                self.assertEqual(tool.main(env, api(files, [OK], **kwargs)), 2)

    def test_same_head_side_pull_request_is_not_evidence_for_main(self):
        head = "c" * 40
        gate = [{"filename": ".github/workflows/ci.yml"}]
        passed = [OK, (tool.SECURITY, "success")]
        main_read = api(gate, passed, head=head, number="4", base_ref="main", base_sha="MAIN")
        # An empty diff against the side base would pass the owner check. It must not.
        side_read = api([], passed, head=head, number="5", base_ref="wip", base_sha="SIDE")

        def both(endpoint):
            if "pulls?" in endpoint or "head=" in endpoint:
                raise AssertionError(endpoint)
            error = None
            for read in (main_read, side_read):
                try:
                    return read(endpoint)
                except subprocess.CalledProcessError as found:
                    error = found
            raise error

        self.assertEqual(tool.missing("o/n", "4", head, "MAIN", both), [tool.OWNER])
        output = StringIO()
        with redirect_stdout(output):
            side = tool.missing("o/n", "5", head, "SIDE", both)
        self.assertEqual(side, [tool.BASE_REF])
        self.assertIn("base wip is not the default branch main", output.getvalue())
        self.assertNotIn(tool.OWNER, side)

    def test_a_retargeted_run_does_not_pass_on_the_old_side_base_sha(self):
        head = "c" * 40
        passed = [OK, (tool.SECURITY, "success")]
        # The live pull request targets main. A rerun of the old run still sends BASE_SHA=SIDE.
        both = api([], passed, head=head, number="4", base_ref="main", base_sha="SIDE", base_status="behind")
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(tool.missing("o/n", "4", head, "SIDE", both), [tool.BASE_REF])
        self.assertIn("event base SIDE is not on the default branch main (behind)", output.getvalue())
        diverged = api([], passed, head=head, number="4", base_ref="main", base_sha="SIDE", base_status="diverged")
        self.assertEqual(tool.missing("o/n", "4", head, "SIDE", diverged), [tool.BASE_REF])
        ahead = api([{"filename": "src/app.py"}], [OK], head=head, base_sha="OLD", base_status="ahead")
        self.assertEqual(tool.missing("o/n", "1", head, "OLD", ahead), [])
        gate = api([{"filename": ".github/workflows/ci.yml"}], [OK, (tool.SECURITY, "success")],
                   head=head, base_sha="OLD", base_status="identical")
        self.assertEqual(tool.missing("o/n", "1", head, "OLD", gate), [tool.OWNER])
        env = {"REPO": "o/n", "PR_NUMBER": "4", "HEAD_SHA": head, "BASE_SHA": "SIDE"}
        unreadable = api([], passed, head=head, number="4", base_ref="main", base_sha="SIDE", base_status=None)
        self.assertEqual(tool.main(env, unreadable), 2)
        unknown = api([], passed, head=head, number="4", base_ref="main", base_sha="SIDE", base_status="unknown")
        self.assertEqual(tool.main(env, unknown), 2)

    def test_cli_exit_codes(self):
        env = {"REPO": "o/n", "PR_NUMBER": "1", "HEAD_SHA": HEAD, "BASE_SHA": "BASE"}
        self.assertEqual(tool.main(env, api([{"filename": "a"}], [OK])), 0)
        self.assertEqual(tool.main(env, api([{"filename": "a"}])), 1)

        def broken(endpoint):
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 403")
        self.assertEqual(tool.main(env, broken), 2)
        self.assertEqual(tool.main({}, api([])), 2)


if __name__ == "__main__":
    unittest.main()

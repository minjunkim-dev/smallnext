"""Which review statuses a pull request head needs, from its changed paths."""

import base64
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_review_status as tool

HEAD = "a" * 40


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


def api(files, statuses=(), author="alice", commits=("alice",), project=None, changed=None, verified=True,
        committer=tool.WEB_FLOW, commit_shas=None, extra_status=None, force_pushes=None, commit_count=None,
        owner="owner", comments=(), agents=None, head=HEAD, compare_files=None, compare_commits=None,
        head_agents=None, force_push_times=None, body=None):
    pull = {"user": {"login": author}, "changed_files": len(files) if changed is None else changed,
            "head": {"sha": head}, "base": {"sha": "BASE"},
            "body": passing_body(head) if body is None else body}
    commit_rows = [{
        "author": {"login": name}, "committer": {"login": committer},
        "commit": {"verification": {"verified": verified},
                   "committer": {"date": f"2020-01-{(index + 1):02d}T00:00:00Z"}},
    } for index, name in enumerate(commits)]
    routes = {
        "repos/o/n/pulls/1": pull,
        "repos/o/n/pulls/1/files?per_page=100": [files],
        "repos/o/n/pulls/1/commits?per_page=100": [commit_rows],
        f"repos/o/n/commits/{head}/status?per_page=100": [{
            "statuses": [{"context": context, "state": state} for context, state in statuses]}],
        "repos/o/n": {"owner": {"login": owner}},
        "repos/o/n/issues/1/comments?per_page=100": [list(comments)],
    }
    if project is not None:
        routes[f"repos/o/n/contents/{tool.PROJECT_PATHS}?ref=BASE"] = {
            "content": base64.b64encode(project.encode()).decode()}
    if agents is not None:
        routes["repos/o/n/contents/AGENTS.md?ref=BASE"] = {
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
        routes["repos/o/n/pulls/1/commits?per_page=100"] = [commit_rows]
    pinned = list(files if compare_files is None else compare_files)
    routes[f"repos/o/n/compare/BASE...{head}"] = {
        "files": pinned, "commits": commit_rows if compare_commits is None else compare_commits}
    if head_agents is not None:
        routes[f"repos/o/n/contents/AGENTS.md?ref={head}"] = {
            "content": base64.b64encode(head_agents.encode()).decode()}
    if extra_status:
        for sha, pairs in extra_status.items():
            routes[f"repos/o/n/commits/{sha}/status?per_page=100"] = [{
                "statuses": [{"context": context, "state": state} for context, state in pairs]}]
    if force_pushes is not None:
        events = []
        for index, sha in enumerate(force_pushes):
            when = (force_push_times[index] if force_push_times is not None
                    else f"2030-01-{(28 - index):02d}T00:00:00Z")
            events.append({"oid": sha, "createdAt": when})
        routes[tool.FORCE_PUSHES + "o/n/1"] = events

    def read(endpoint):
        if endpoint not in routes:
            raise subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
        return routes[endpoint]
    return read


def run(read):
    return tool.missing("o/n", "1", HEAD, "BASE", read)


def comment(body, login="owner"):
    return {"user": {"login": login}, "body": body}


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
     return 0
+    return 2
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

    def test_an_unchanged_diff_reuses_the_prior_success(self):
        files = [{"filename": "src/app.py"}]
        read = api(files, commit_shas=["OLD", HEAD], extra_status={"OLD": [OK]}, force_pushes=[])
        same = diffs({"OLD": ADDED, HEAD: SHIFTED})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, same), [])
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
        self.assertIn("repos/o/n/commits/MID/status?per_page=100", seen)

    def test_a_rebase_parent_can_carry_the_status(self):
        files = [{"filename": "src/app.py"}]
        read = api(files, commit_shas=[HEAD], force_pushes=["OLD"], extra_status={"OLD": [OK]})
        self.assertEqual(tool.missing("o/n", "1", HEAD, "BASE", read, diffs({"OLD": ADDED, HEAD: SHIFTED})), [])

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
        self.assertIn("repos/o/n/commits/MID/status?per_page=100", seen)

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
        self.assertNotEqual(tool.diff_identity(ADDED), tool.diff_identity(SHIFTED.replace("+    return 2", "+        return 2")))
        self.assertEqual(tool.diff_identity(""), "empty")
        self.assertIsNone(tool.diff_identity('{"message":"diff too large"}'))
        self.assertIsNone(tool.diff_identity("diff --git a/a b/a\nnot a diff line\n"))
        binary = "diff --git a/a.bin b/a.bin\nindex 1111111..2222222 100644\nBinary files a/a.bin and b/a.bin differ\n"
        other = binary.replace("1111111..2222222", "1111111..3333333")
        self.assertNotEqual(tool.diff_identity(binary), tool.diff_identity(other))
        self.assertIsNone(tool.diff_identity(binary.replace("index 1111111..2222222 100644\n", "")))
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

    def test_owner_comment_matches_only_this_head(self):
        head = "a" * 40
        other = "b" * 40
        files = [{"filename": "templates/review-status.yml"}]
        reviews = [OK, (tool.SECURITY, "success")]

        def check(comments, expected, **kwargs):
            read = api(files, reviews, comments=comments, head=head, **kwargs)
            self.assertEqual(tool.missing("o/n", "1", head, "BASE", read), expected)

        check([comment(f"한쪽 문 승인: {head} 메모", login="Owner")], [], owner="owner")
        check([comment(f"한쪽 문 승인: {head}\r\n메모")], [])
        check([comment(f"한쪽 문 승인: {other}")], [tool.OWNER])
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
            if "/compare/" in endpoint:
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

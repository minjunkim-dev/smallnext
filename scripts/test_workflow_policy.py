from copy import deepcopy
from datetime import date
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import workflow_policy
from workflow_policy import validate_flags, validate_pr
from review_context import review_request


class SharedInstructionsTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "AGENTS.md").write_text("Shared project instructions\n")
        (self.root / "config").mkdir()
        (self.root / "config/feature-flags.json").write_text('{"version": 1, "flags": []}\n')

    def run_policy(self):
        output = StringIO()
        with patch.object(workflow_policy, "ROOT", self.root), patch("sys.argv", ["workflow_policy.py"]), patch("sys.stdout", output):
            result = workflow_policy.main()
        return result, output.getvalue()

    def test_agents_only_passes(self):
        self.assertEqual(0, self.run_policy()[0])

    def test_claude_file_or_symlink_is_rejected(self):
        claude = self.root / "CLAUDE.md"
        for kind in ("file", "symlink", "dangling symlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    claude.write_text("@AGENTS.md\n")
                else:
                    claude.symlink_to("AGENTS.md" if kind == "symlink" else "missing.md")
                result, output = self.run_policy()
                self.assertEqual(1, result)
                self.assertIn("Use AGENTS.md only", output)
                claude.unlink()

    def test_missing_agents_is_rejected(self):
        (self.root / "AGENTS.md").unlink()
        result, output = self.run_policy()
        self.assertEqual(1, result)
        self.assertIn("AGENTS.md is required", output)


class ConventionsTest(unittest.TestCase):
    def test_small_changes_and_numbered_work(self):
        for title, branch, body in [
            ("chore: bootstrap native apps and Rust API monorepo", "chore/initial-monorepo-setup", "Refs #13"),
            ("feat(ios): add goal split card", "feat/17-goal-split", "Closes #17"),
            ("fix(api)!: change action contract", "codex/fix-action", "Refs #18"),
            ("chore(deps): bump checkout", "dependabot/github_actions/actions/checkout-7", ""),
            ("docs: add guide", "docs/a", ""),
        ]:
            with self.subTest(branch=branch):
                self.assertEqual([], validate_pr(title, branch, body))

    def test_long_title_exemption_requires_dependabot_author(self):
        title = "chore: bump androidx.compose:compose-bom from 2026.05.00 to 2026.09.00 in /apps/android"
        branch = "dependabot/gradle/apps/android/androidx.compose-compose-bom-2026.09.00"
        self.assertEqual([], validate_pr(title, branch, "", "dependabot[bot]"))
        self.assertTrue(validate_pr(title, branch, "", "minjunkim-dev"))

    def test_rejects_missing_issue_unsafe_metadata_and_invalid_names(self):
        for title, branch, body in [
            ("feat: add split", "feat/goal-split", "Refs #17"),
            ("feat: add split", "feat/17-split", ""),
            ("docs: Add guide", "docs/guide", ""),
            ("docs: add guide.", "docs/guide", ""),
            ("docs: add guide\nrun a command", "docs/guide", ""),
            ("docs: " + "a" * 70, "docs/guide", ""),
            ("fix: save data", "fix/0-save", "Refs #18"),
        ]:
            with self.subTest(branch=branch, title=title):
                self.assertTrue(validate_pr(title, branch, body))


class FlagsTest(unittest.TestCase):
    def setUp(self):
        self.flag = {"key": "goal_resplitting", "default": False, "phase": "development", "owner": "minjunkim-dev", "issue": 17, "remove_by": "2026-11-03"}
        self.today = date(2026, 10, 3)

    def test_empty_and_default_off(self):
        self.assertEqual([], validate_flags({"version": 1, "flags": []}, self.today))
        self.assertEqual([], validate_flags({"version": 1, "flags": [self.flag]}, self.today))

    def test_unfinished_on_missing_owner_invalid_issue_and_expiry_fail(self):
        for key, value in [("default", True), ("default", "false"), ("owner", ""), ("issue", True), ("remove_by", "2026-10-02"), ("phase", "unknown"), ("key", "GoalSplit")]:
            flag = dict(self.flag, **{key: value})
            with self.subTest(key=key):
                self.assertTrue(validate_flags({"version": 1, "flags": [flag]}, self.today))

    def test_duplicate_and_malformed(self):
        self.assertTrue(validate_flags({"version": 1, "flags": [self.flag, self.flag]}, self.today))
        for value in [[], {"version": True, "flags": []}, {"version": 1, "flags": [None]}]:
            self.assertTrue(validate_flags(value, self.today))

    def test_released_requires_approval(self):
        flag = dict(self.flag, phase="released", default=True)
        self.assertTrue(validate_flags({"version": 1, "flags": [flag]}, self.today))
        flag["release_issue"] = 19
        self.assertEqual([], validate_flags({"version": 1, "flags": [flag]}, self.today))


class PolicyRootTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        source = Path(__file__).resolve().parent / "workflow_policy.py"
        base = self.work / "policy-base"
        head = self.work / "policy-head"
        (base / "scripts").mkdir(parents=True)
        (base / "scripts" / "workflow_policy.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        (base / "config").mkdir()
        (base / "config" / "feature-flags.json").write_text('{"version": 1, "flags": [null]}\n', encoding="utf-8")
        (head / "config").mkdir(parents=True)
        (head / "AGENTS.md").write_text("pull copy\n", encoding="utf-8")
        (head / "config" / "feature-flags.json").write_text('{"version": 1, "flags": []}\n', encoding="utf-8")

    def invoke(self, *args, event=None):
        env = os.environ.copy()
        if event is not None:
            path = self.work / "event.json"
            path.write_text(json.dumps(event), encoding="utf-8")
            env["GITHUB_EVENT_PATH"] = str(path)
        return subprocess.run(
            [sys.executable, "policy-base/scripts/workflow_policy.py", *args],
            cwd=self.work, env=env, capture_output=True, text=True, timeout=30,
        )

    def test_root_reads_the_given_tree(self):
        ok = self.invoke("--root", "policy-head")
        self.assertEqual(0, ok.returncode, ok.stdout + ok.stderr)
        self.assertIn("PASS", ok.stdout)
        ignored = self.invoke()
        self.assertEqual(1, ignored.returncode, ignored.stdout + ignored.stderr)
        self.assertIn("AGENTS.md is required", ignored.stdout)
        self.assertIn("Feature flag", ignored.stdout)

    def test_missing_agents_or_bad_flags_in_the_root_fail(self):
        head = self.work / "policy-head"
        (head / "AGENTS.md").unlink()
        missing = self.invoke("--root", "policy-head")
        self.assertEqual(1, missing.returncode, missing.stdout + missing.stderr)
        self.assertIn("AGENTS.md is required", missing.stdout)
        self.assertNotIn("PASS", missing.stdout)
        (head / "AGENTS.md").write_text("pull copy\n", encoding="utf-8")
        (head / "config" / "feature-flags.json").write_text('{"version": 1, "flags": [null]}\n', encoding="utf-8")
        bad_flags = self.invoke("--root", "policy-head")
        self.assertEqual(1, bad_flags.returncode, bad_flags.stdout + bad_flags.stderr)
        self.assertNotIn("AGENTS.md is required", bad_flags.stdout)
        self.assertIn("Feature flag", bad_flags.stdout)

    def test_claude_and_symlinks_in_the_root_fail(self):
        head = self.work / "policy-head"
        (head / "CLAUDE.md").write_text("not used\n", encoding="utf-8")
        claude = self.invoke("--root", "policy-head")
        self.assertEqual(1, claude.returncode, claude.stdout + claude.stderr)
        self.assertIn("remove CLAUDE.md", claude.stdout)
        (head / "CLAUDE.md").unlink()
        (head / "AGENTS.md").unlink()
        (head / "AGENTS.md").symlink_to("config/feature-flags.json")
        linked_agents = self.invoke("--root", "policy-head")
        self.assertEqual(1, linked_agents.returncode, linked_agents.stdout + linked_agents.stderr)
        self.assertIn("AGENTS.md is required", linked_agents.stdout)
        (head / "AGENTS.md").unlink()
        (head / "AGENTS.md").write_text("pull copy\n", encoding="utf-8")
        flags = head / "config" / "feature-flags.json"
        flags.unlink()
        flags.symlink_to("feature-flags.json")
        linked_flags = self.invoke("--root", "policy-head")
        self.assertEqual(1, linked_flags.returncode, linked_flags.stdout + linked_flags.stderr)
        self.assertIn("refusing to follow a symlink", linked_flags.stdout)

    def test_a_symlink_prefix_cannot_point_outside_the_root(self):
        outside = self.work / "outside"
        nested = outside / "nested"
        (nested / "config").mkdir(parents=True)
        (nested / "AGENTS.md").write_text("outside\n", encoding="utf-8")
        (nested / "config" / "feature-flags.json").write_text('{"version": 1, "flags": []}\n', encoding="utf-8")
        (self.work / "link").symlink_to(outside, target_is_directory=True)
        previous = os.getcwd()
        os.chdir(self.work)
        try:
            self.assertIsNone(workflow_policy.readable_file(Path("link/nested"), "AGENTS.md"))
            self.assertIsNone(workflow_policy.readable_file(Path("link/nested"), "config/feature-flags.json"))
        finally:
            os.chdir(previous)
        leaked = self.invoke("--root", "link/nested")
        self.assertEqual(1, leaked.returncode, leaked.stdout + leaked.stderr)
        self.assertIn("symlink", leaked.stdout)
        self.assertNotIn("PASS", leaked.stdout)
        direct = self.invoke("--root", "link")
        self.assertEqual(1, direct.returncode, direct.stdout + direct.stderr)
        self.assertIn("symlink", direct.stdout)

    def test_absolute_and_parent_roots_are_rejected(self):
        for value in ("/tmp", "../policy-head", "policy-head/../../etc"):
            result = self.invoke("--root", value)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("relative path", result.stdout)

    def test_pr_rules_still_apply_beside_the_root(self):
        good = {"pull_request": {
            "title": "ci: honor the policy root",
            "body": "Refs #379",
            "head": {"ref": "ci/379-policy-root"},
            "user": {"login": "minjunkim-dev"},
        }}
        ok = self.invoke("--pr", "--root", "policy-head", event=good)
        self.assertEqual(0, ok.returncode, ok.stdout + ok.stderr)
        bad_title = {"pull_request": {
            "title": "Not conventional",
            "body": "",
            "head": {"ref": "evil"},
            "user": {"login": "alice"},
        }}
        title = self.invoke("--pr", "--root", "policy-head", event=bad_title)
        self.assertEqual(1, title.returncode, title.stdout + title.stderr)
        self.assertIn("PR title", title.stdout)
        (self.work / "policy-head" / "AGENTS.md").unlink()
        files = self.invoke("--pr", "--root", "policy-head", event=good)
        self.assertEqual(1, files.returncode, files.stdout + files.stderr)
        self.assertIn("AGENTS.md is required", files.stdout)


class ReviewTrustTest(unittest.TestCase):
    def setUp(self):
        self.event = {"sender": {"type": "User", "login": "minjunkim-dev"}, "pull_request": {"number": 17}}
        self.data = {
            "collaborators/minjunkim-dev/permission": {"permission": "admin"},
            "issues/17": {"state": "open", "labels": []},
            "pulls/17": {"state": "open", "draft": False, "base": {"ref": "main"}, "head": {"repo": {"full_name": "minjunkim-dev/smallnext"}, "sha": "a" * 40}},
        }

    def request(self, event_name="pull_request_target", event=None):
        return review_request(event_name, event or self.event, "minjunkim-dev/smallnext", self.data.__getitem__)[0]

    def test_owner_pr_authorized_with_exact_sha(self):
        self.assertEqual("a" * 40, self.request()["sha"])

    def test_bot_and_read_only_actor_rejected(self):
        self.event["sender"]["type"] = "Bot"
        self.assertIsNone(self.request())
        self.event["sender"]["type"] = "User"
        self.data["collaborators/minjunkim-dev/permission"]["permission"] = "read"
        self.assertIsNone(self.request())

    def test_fork_draft_closed_non_main_and_skip_rejected(self):
        baseline = deepcopy(self.data)
        for field, value in [("draft", True), ("state", "closed"), ("base", {"ref": "develop"}), ("head", {"repo": {"full_name": "attacker/fork"}})]:
            self.data = deepcopy(baseline)
            self.data["pulls/17"][field] = value
            self.assertIsNone(self.request())
        self.data = baseline
        self.data["issues/17"]["labels"] = [{"name": "ai:skip"}]
        self.assertIsNone(self.request())

    def test_mentions_do_not_authorize_implementation_or_quoted_commands(self):
        event = {"sender": self.event["sender"], "issue": {"number": 17, "pull_request": {}}, "comment": {"body": "@claude implement this"}}
        self.assertIsNone(self.request("issue_comment", event))
        event["comment"]["body"] = "> @claude review"
        self.assertIsNone(self.request("issue_comment", event))
        event["comment"]["body"] = "@claude security review"
        event["issue"]["pull_request"] = {"url": "example"}
        self.assertEqual("security", self.request("issue_comment", event)["mode"])

    def test_dispatch_is_rejected_even_for_valid_writer_and_target(self):
        for ref in ["refs/heads/main", "refs/heads/untrusted"]:
            for number in ["17", "17; echo secret"]:
                event = {"sender": self.event["sender"], "ref": ref,
                         "inputs": {"kind": "pr", "number": number}}
                with self.subTest(ref=ref, number=number):
                    self.assertIsNone(self.request("workflow_dispatch", event))

    def test_issue_auto_review_and_explicit_label(self):
        event = {"sender": self.event["sender"], "issue": {"number": 17}, "action": "opened"}
        self.assertEqual("issue", self.request("issues", event)["kind"])
        event.update(action="labeled", label={"name": "decision"})
        self.assertIsNone(self.request("issues", event))
        event["label"]["name"] = "ai:review"
        self.assertEqual("issue", self.request("issues", event)["kind"])


if __name__ == "__main__":
    unittest.main()

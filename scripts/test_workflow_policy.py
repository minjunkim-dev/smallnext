from copy import deepcopy
from datetime import date
import unittest

from workflow_policy import validate_flags, validate_pr
from review_context import review_request


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

    def test_dispatch_rejects_injected_number(self):
        event = {"sender": self.event["sender"], "inputs": {"kind": "pr", "number": "17; echo secret"}}
        self.assertIsNone(self.request("workflow_dispatch", event))


if __name__ == "__main__":
    unittest.main()

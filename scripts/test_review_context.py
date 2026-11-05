"""Smallnext review authorization checks.

These tests lived in test_workflow_policy.py. That file is now a hashed
repo-baseline copy, so the project-specific cases stay here.
"""

from copy import deepcopy
import unittest

from review_context import review_request


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

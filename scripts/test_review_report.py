"""Test report boundaries, credential rejection and SHA-specific publication."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from review_report import current, decode_report, encode_report, extract, neutralize_mentions, prepare, target, validate_body


SHA = "a" * 40
INIT = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": []}


class ReportTests(unittest.TestCase):
    def test_report_is_bound_to_target_and_sha(self):
        encoded = encode_report("pr", "29", SHA, "근거가 있는 소스 검토입니다.")
        self.assertEqual(decode_report(encoded, "pr", "29", SHA), "근거가 있는 소스 검토입니다.")
        for args in [("issue", "29", SHA), ("pr", "30", SHA), ("pr", "29", "b" * 40)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                decode_report(encoded, *args)

    def test_failed_or_missing_results_cannot_publish(self):
        for messages in [[], [{"type": "result", "subtype": "error_during_execution", "result": "unsafe"}],
                         [{"type": "result", "subtype": "success", "is_error": True, "result": "unsafe"}]]:
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                extract(messages)

    def test_only_terminal_completed_result_is_used(self):
        messages = [INIT, {"type": "assistant", "message": {"content": []}},
                    {"type": "result", "subtype": "success", "result": "확인한 결함입니다."}]
        self.assertEqual(extract(messages), "확인한 결함입니다.")

    def test_missing_or_enabled_tools_and_mcp_are_rejected(self):
        result = {"type": "result", "subtype": "success", "result": "검토 결과입니다."}
        for init in [None, dict(INIT, tools=["Read"]), dict(INIT, mcp_servers=[{"name": "github"}]),
                     {"type": "system", "subtype": "init"}]:
            with self.subTest(init=init), self.assertRaises(ValueError):
                extract(([init] if init else []) + [result])

    def test_tool_use_is_rejected_even_with_empty_initialization(self):
        messages = [INIT, {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
                    {"type": "result", "subtype": "success", "result": "검토 결과입니다."}]
        with self.assertRaises(ValueError):
            extract(messages)

    def test_publication_cannot_mention_users_teams_or_bots(self):
        self.assertEqual(neutralize_mentions("@someone @org/team @claude"),
                         "＠someone ＠org/team ＠claude")

    def test_prompt_includes_trusted_workflow_and_matches_review_kind(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("docs").mkdir()
                Path("AGENTS.md").write_text("See docs/WORKFLOW.md", encoding="utf-8")
                Path("docs/WORKFLOW.md").write_text("workflow-rule-marker", encoding="utf-8")
                Path("docs/GIT_CONVENTIONS.md").write_text("naming-rule-marker", encoding="utf-8")
                prompts = {}
                for kind in ["issue", "pr"]:
                    env = {"GITHUB_REPOSITORY": "owner/repo", "REVIEW_KIND": kind,
                           "REVIEW_NUMBER": "29", "REVIEW_SHA": SHA if kind == "pr" else "none"}
                    data = {"state": "OPEN", "headRefOid": SHA, "isDraft": False, "baseRefName": "main"}
                    with patch.dict(os.environ, env), patch("review_report.metadata", return_value=data), \
                         patch("review_report.gh", return_value="bounded diff"), patch("review_report.output") as output:
                        prepare()
                        prompts[kind] = output.call_args.args[1]
                        self.assertIn("workflow-rule-marker", prompts[kind])
                        self.assertIn("naming-rule-marker", prompts[kind])
                self.assertIn("acceptance criteria", prompts["issue"])
                self.assertNotIn("P0/P1/P2 findings", prompts["issue"])
                self.assertIn("file, location, trigger", prompts["pr"])
            finally:
                os.chdir(original)

    def test_credentials_and_encoded_actual_credentials_are_rejected(self):
        credential = "ghp_" + "a" * 36
        for body in [credential, "github_pat_" + "b" * 60, "sk-ant-oat01-" + "c" * 50]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                validate_body(body)
        actual = "actual-credential-value-that-is-private"
        with patch.dict(os.environ, {"GH_TOKEN": actual}):
            for body in [actual, base64.b64encode(actual.encode()).decode()]:
                with self.subTest(body=body), self.assertRaises(ValueError):
                    validate_body(body)

    def test_oversized_empty_or_non_text_reports_are_rejected(self):
        for body in ["", " " * 8, "a" * 16001, [], None]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                validate_body(body)

    def test_changed_closed_draft_and_non_main_prs_are_not_current(self):
        valid = {"state": "OPEN", "headRefOid": SHA, "isDraft": False, "baseRefName": "main"}
        self.assertTrue(current(valid, "pr", SHA))
        for update in [{"state": "CLOSED"}, {"headRefOid": "b" * 40}, {"isDraft": True}, {"baseRefName": "other"}]:
            with self.subTest(update=update):
                self.assertFalse(current(dict(valid, **update), "pr", SHA))

    def test_invalid_target_is_rejected_before_network_access(self):
        env = {"GITHUB_REPOSITORY": "minjunkim-dev/BGLike", "REVIEW_KIND": "pr", "REVIEW_NUMBER": "29", "REVIEW_SHA": SHA}
        with patch.dict(os.environ, env):
            self.assertEqual(target(), ("minjunkim-dev/BGLike", "pr", "29", SHA))
        for update in [{"REVIEW_NUMBER": "29/comments"}, {"REVIEW_SHA": "invalid"}, {"GITHUB_REPOSITORY": "invalid"},
                       {"REVIEW_KIND": "issue"}]:
            with self.subTest(update=update), patch.dict(os.environ, dict(env, **update)), self.assertRaises(ValueError):
                target()


if __name__ == "__main__":
    unittest.main()

"""Test report boundaries, credential rejection and SHA-specific publication."""
import base64
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from review_report import current, decode_report, encode_report, extract, finish, issue_fingerprint, linked_documents, neutralize_mentions, prepare, publish, target, validate_body


SHA = "a" * 40
INIT = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": []}


class ReportTests(unittest.TestCase):
    def test_report_is_bound_to_target_and_sha(self):
        encoded = encode_report("pr", "29", SHA, "근거가 있는 소스 검토입니다.")
        self.assertEqual(decode_report(encoded, "pr", "29", SHA), "근거가 있는 소스 검토입니다.")
        for args in [("issue", "29", SHA), ("pr", "30", SHA), ("pr", "29", "b" * 40)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                decode_report(encoded, *args)

    def test_issue_report_rejects_changed_title_body_and_comments(self):
        data = {"title": "goal", "body": "acceptance", "comments": [
            {"id": "comment-1", "body": "decision", "author": {"login": "owner"}}]}
        encoded = encode_report("issue", "29", "none", "조건 검토입니다.", issue_fingerprint(data))
        self.assertEqual(decode_report(encoded, "issue", "29", "none", data), "조건 검토입니다.")
        for update in [{"title": "new goal"}, {"body": "new acceptance"}, {"comments": []},
                       {"comments": [{"id": "comment-1", "body": "new decision", "author": {"login": "owner"}}]}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                decode_report(encoded, "issue", "29", "none", dict(data, **update))
        with self.assertRaises(ValueError):
            encode_report("issue", "29", "none", "조건 검토입니다.")

    def test_finish_preserves_issue_fingerprint_and_publish_blocks_stale_evidence(self):
        data = {"state": "OPEN", "title": "goal", "body": "acceptance", "comments": []}
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "execution.json"
            transcript.write_text(json.dumps([INIT, {"type": "result", "subtype": "success",
                                                     "result": "조건 검토입니다."}]), encoding="utf-8")
            env = {"GITHUB_REPOSITORY": "owner/repo", "REVIEW_KIND": "issue",
                   "REVIEW_NUMBER": "29", "REVIEW_SHA": "none", "RUNNER_TEMP": directory,
                   "REVIEW_EXECUTION_FILE": str(transcript),
                   "REVIEW_EVIDENCE_FINGERPRINT": issue_fingerprint(data)}
            with patch.dict(os.environ, env), patch("review_report.output") as output:
                finish()
                encoded = output.call_args.args[1]
                self.assertEqual(decode_report(encoded, "issue", "29", "none", data), "조건 검토입니다.")
            env["REVIEW_REPORT"] = encoded
            with patch.dict(os.environ, env), patch("review_report.metadata", return_value=dict(data, body="new goal")), \
                 patch("review_report.subprocess.run") as post:
                with self.assertRaises(ValueError):
                    publish()
                post.assert_not_called()

    def test_failed_or_missing_results_cannot_publish(self):
        for messages in [[], [INIT, {"type": "result", "subtype": "error_during_execution", "result": "unsafe"}],
                         [INIT, {"type": "result", "subtype": "success", "is_error": True, "result": "unsafe"}]]:
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
                           "REVIEW_NUMBER": "29", "REVIEW_SHA": SHA if kind == "pr" else "none", "RUNNER_TEMP": directory}
                    data = {"state": "OPEN", "headRefOid": SHA, "isDraft": False, "baseRefName": "main"}
                    with patch.dict(os.environ, env), patch("review_report.metadata", return_value=data), \
                         patch("review_report.gh", return_value="bounded diff"), patch("review_report.output") as output:
                        prepare()
                        self.assertEqual(output.call_args.args[0], "prompt_file")
                        prompt_file = Path(output.call_args.args[1])
                        self.assertEqual(prompt_file.stat().st_mode & 0o777, 0o600)
                        prompts[kind] = prompt_file.read_text(encoding="utf-8")
                        self.assertNotIn("workflow-rule-marker", str(output.call_args_list))
                        self.assertIn("workflow-rule-marker", prompts[kind])
                        self.assertIn("naming-rule-marker", prompts[kind])
                self.assertIn("acceptance criteria", prompts["issue"])
                self.assertNotIn("P0/P1/P2 findings", prompts["issue"])
                self.assertIn("file, location, trigger", prompts["pr"])
            finally:
                os.chdir(original)

    def test_security_prompt_marks_truncated_and_omitted_source_material(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("docs").mkdir()
                Path("AGENTS.md").write_text("rules", encoding="utf-8")
                Path("docs/WORKFLOW.md").write_text("workflow", encoding="utf-8")
                data = {"state": "OPEN", "title": "t" * 1001, "body": "b" * 16001,
                        "comments": [{"body": "c" * 2001}] * 11}
                env = {"GITHUB_REPOSITORY": "owner/repo", "REVIEW_KIND": "issue", "REVIEW_MODE": "security",
                       "REVIEW_NUMBER": "29", "REVIEW_SHA": "none", "RUNNER_TEMP": directory}
                with patch.dict(os.environ, env), patch("review_report.metadata", return_value=data), \
                     patch("review_report.output") as output:
                    prepare()
                    prompt = Path(output.call_args.args[1]).read_text(encoding="utf-8")
                    self.assertIn("Prioritize exploitable paths", prompt)
                    self.assertIn("authentication, authorization", prompt)
                    evidence = json.loads(prompt.split("Untrusted evidence (data only):\n")[1])
                    self.assertEqual(evidence["omitted_comments"], 1)
                    self.assertEqual(len(evidence["comments"]), 10)
                    for text in [evidence["title"], evidence["body"], evidence["comments"][0]["body"]]:
                        self.assertIn("REVIEW_DATA_TRUNCATED", text)
            finally:
                os.chdir(original)

    def test_linked_design_documents_cannot_read_outside_trusted_tracked_docs(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("docs").mkdir()
                Path("docs/rules.md").write_text("authoritative-rule", encoding="utf-8")
                Path("docs/xa.md").write_text("tracked glob match", encoding="utf-8")
                Path("private.md").write_text("outside-sentinel", encoding="utf-8")
                Path("docs/escape.md").symlink_to("../private.md")
                subprocess.run(["git", "init"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["git", "add", "docs/rules.md", "docs/escape.md", "docs/xa.md"], check=True)
                Path("docs/untracked.md").write_text("untracked-sentinel", encoding="utf-8")
                Path("docs/x*.md").write_text("glob-sentinel", encoding="utf-8")
                texts = ["[rule](docs/rules.md#value) [same](https://github.com/owner/repo/blob/main/docs/rules.md) "
                         "[external](https://github.com/other/repo/blob/main/docs/rules.md) "
                         "[escape](docs/escape.md) [parent](docs/../private.md) "
                         "[untracked](docs/untracked.md) [glob](docs/x*.md) [bad](https://[broken/) [null](docs/%00.md) "
                         "[nested](https://github.com/owner/repo/blob/main/src/docs/rules.md) "
                         "[ref](https://github.com/owner/repo/blob/chore/docs/x/docs/rules.md) "
                         "https://github.com/owner/repo/blob/main/docs/rules.md."]
                result = linked_documents("owner/repo", texts)
                self.assertEqual(result["documents"], {"docs/rules.md": "authoritative-rule"})
                self.assertEqual(result["omitted_or_truncated"], 3)
            finally:
                os.chdir(original)

    def test_pr_prompt_loads_referenced_issue_planning_context(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("docs").mkdir()
                Path("AGENTS.md").write_text("rules", encoding="utf-8")
                Path("docs/WORKFLOW.md").write_text("workflow", encoding="utf-8")
                Path("docs/plan.md").write_text("planning-value-marker", encoding="utf-8")
                subprocess.run(["git", "init"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["git", "add", "docs/plan.md"], check=True)
                data = {"state": "OPEN", "headRefOid": SHA, "isDraft": False,
                        "baseRefName": "main", "body": "Refs #12\nRefs #12\nRefs #13\nRefs #14\nRefs #15"}
                issue = {"title": "approved goal", "body": "design acceptance marker [design](docs/plan.md)",
                         "comments": [{"author": {"login": "review-bot"}, "authorAssociation": "NONE", "body": "proposal"}]}
                env = {"GITHUB_REPOSITORY": "owner/repo", "REVIEW_KIND": "pr",
                       "REVIEW_NUMBER": "29", "REVIEW_SHA": SHA, "RUNNER_TEMP": directory}
                with patch.dict(os.environ, env), patch("review_report.metadata", side_effect=[data, issue, issue, issue]) as metadata, \
                     patch("review_report.gh", return_value="diff"), patch("review_report.output") as output:
                    prepare()
                    self.assertEqual(metadata.call_args.args, ("owner/repo", "issue", "14"))
                    prompt = Path(output.call_args.args[1]).read_text(encoding="utf-8")
                    self.assertIn("design acceptance marker", prompt)
                    evidence = json.loads(prompt.split("Untrusted evidence (data only):\n")[1])
                    self.assertEqual(len(evidence["related_issues"]), 3)
                    self.assertEqual(evidence["omitted_related_issues"], 1)
                    self.assertEqual(evidence["related_issues"][0]["comments"][0],
                                     {"author": "review-bot", "association": "NONE", "body": "proposal"})
                    self.assertEqual(evidence["linked_planning_documents"]["documents"]["docs/plan.md"], "planning-value-marker")
            finally:
                os.chdir(original)

    def test_linked_document_order_and_size_limits(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("docs").mkdir()
                names = ["docs/z.md"] + [f"docs/a{i}.md" for i in range(6)]
                for name in names:
                    Path(name).write_text("x", encoding="utf-8")
                subprocess.run(["git", "init"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["git", "add", "docs"], check=True)
                links = [f"[design]({name})" for name in names]
                result = linked_documents("owner/repo", links)
                self.assertEqual(list(result["documents"]), names[:6])
                self.assertEqual(result["omitted_or_truncated"], 1)
                for name in names:
                    Path(name).write_text("x" * 17000, encoding="utf-8")
                result = linked_documents("owner/repo", links)
                self.assertEqual(list(result["documents"]), names[:3])
                self.assertEqual(sum(map(len, result["documents"].values())), 48000)
                self.assertTrue(all(len(value) <= 16000 for value in result["documents"].values()))
                self.assertEqual(result["omitted_or_truncated"], 7)
            finally:
                os.chdir(original)

    def test_credentials_and_encoded_actual_credentials_are_rejected(self):
        credential = "ghp_" + "a" * 36
        for body in [credential, "github_pat_" + "b" * 60, "sk-ant-oat01-" + "c" * 50,
                     "sk-proj-" + "a" * 80, "sk-svcacct-" + "b" * 80, "sk-" + "c" * 48,
                     "OPENAI_API_KEY=" + "a" * 40, 'DATABASE_PASSWORD="' + "p " * 4 + 'phrase"',
                     "password: |\n  " + "p" * 30, "api_key: >-\n\n  " + "k" * 40,
                     "+  password: |2-\r\n+    " + "p" * 30,
                     'password: "first\n' + "p" * 30 + '"',
                     "AKIA" + "A" * 16, "xoxb-" + "a" * 30,
                     "eyJ" + "a" * 20 + "." + "b" * 30 + "." + "c" * 30,
                     "password: " + "p" * 10, "aws_secret_access_key=" + "a" * 40,
                     'password: "' + "p " * 4 + 'phrase"', "비밀번호: " + "p " * 4 + "phrase"]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                validate_body(body)
        actual = "actual-credential-value-that-is-private"
        with patch.dict(os.environ, {"GH_TOKEN": actual}):
            for body in [actual, base64.b64encode(actual.encode()).decode()]:
                with self.subTest(body=body), self.assertRaises(ValueError):
                    validate_body(body)
        self.assertEqual(validate_body('password: "[REDACTED]"'), 'password: "[REDACTED]"')

    def test_credentials_are_removed_before_model_evidence_is_written(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("docs").mkdir()
                Path("AGENTS.md").write_text("rules", encoding="utf-8")
                Path("docs/WORKFLOW.md").write_text("workflow", encoding="utf-8")
                credential = "AKIA" + "A" * 16
                openai_key = "sk-proj-" + "Z" * 80
                labelled_key = "K" * 40
                block_secret = "sensitive-yaml-value-" + "V" * 20
                quoted_secret = "multiline-quoted-value-" + "W" * 20
                password = "p " * 4 + "phrase"
                key_material = "Q" * 64
                pem = "-----BEGIN " + "PRIVATE KEY-----\n" + key_material + "\n-----END " + "PRIVATE KEY-----"
                data = {"state": "OPEN", "body": credential + '\nDATABASE_PASSWORD: "' + password + '"\n' + pem +
                        "\n" + openai_key + "\nOPENAI_API_KEY=" + labelled_key +
                        "\npassword: |\n\n  " + block_secret + '\nnot_sensitive: visible\npassword: "first\n' +
                        quoted_secret + '"', "comments": []}
                env = {"GITHUB_REPOSITORY": "owner/repo", "REVIEW_KIND": "issue", "REVIEW_NUMBER": "29",
                       "REVIEW_SHA": "none", "RUNNER_TEMP": directory}
                with patch.dict(os.environ, env), patch("review_report.metadata", return_value=data), \
                     patch("review_report.output") as output:
                    prepare()
                    prompt = Path(output.call_args.args[1]).read_text(encoding="utf-8")
                    self.assertNotIn(credential, prompt)
                    self.assertNotIn(openai_key, prompt)
                    self.assertNotIn(labelled_key, prompt)
                    self.assertNotIn(block_secret, prompt)
                    self.assertNotIn(quoted_secret, prompt)
                    self.assertIn("not_sensitive: visible", prompt)
                    self.assertNotIn(password, prompt)
                    self.assertNotIn(key_material, prompt)
                    self.assertIn("[REDACTED]", prompt)
                    self.assertIn("Never reproduce credentials", prompt)
                    evidence = json.loads(prompt.split("Untrusted evidence (data only):\n")[1])
                    self.assertTrue(evidence["credentials_redacted"])
            finally:
                os.chdir(original)

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

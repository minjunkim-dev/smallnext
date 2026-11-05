"""PR conventions, and the optional AGENTS.md and feature-flag checks."""

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
from workflow_policy import parse_author, validate_body, validate_flags, validate_pr

ROOT = Path(__file__).resolve().parents[1]
BODY = """Author: Cursor / grok-4.7

## Summary
why

## Evidence
ran

## Merge Danger
Door: 되돌리기 쉬움
"""


class SharedInstructionsTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "AGENTS.md").write_text("Shared project instructions\n")
        (self.root / "config").mkdir()
        (self.root / "config/feature-flags.json").write_text('{"version": 1, "flags": []}\n')

    def run_policy(self, argv=None):
        output = []

        def capture(text=""):
            output.append(text)

        with patch.object(workflow_policy, "ROOT", self.root), patch("sys.argv", argv or ["workflow_policy.py"]), patch("builtins.print", capture):
            result = workflow_policy.main()
        return result, "\n".join(output)

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

    def test_config_can_turn_repo_specific_checks_off(self):
        (self.root / "AGENTS.md").unlink()
        (self.root / "config/feature-flags.json").unlink()
        (self.root / "CLAUDE.md").write_text("@AGENTS.md\n")
        github = self.root / ".github"
        github.mkdir()
        (github / "workflow-policy.json").write_text(json.dumps({
            "require_agents_md": False,
            "reject_claude_md": False,
            "feature_flags": False,
            "bot_branch_prefixes": ["claude", "codex", "dependabot", "cursor"],
        }))
        self.assertEqual(0, self.run_policy()[0])


class ConventionsTest(unittest.TestCase):
    def test_small_changes_and_numbered_work(self):
        for title, branch, body in [
            ("chore: bootstrap native apps and Rust API monorepo", "chore/initial-monorepo-setup", "Refs #13"),
            ("feat(ios): add goal split card", "feat/17-goal-split", "Closes #17"),
            ("fix(api)!: change action contract", "codex/fix-action", "Refs #18"),
            ("chore(deps): bump checkout", "dependabot/github_actions/actions/checkout-7", ""),
            ("docs: add guide", "docs/a", ""),
            ("docs: 안내를 더한다", "docs/guide", ""),
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
            ("refactor: 묶는다", "refactor/no-issue", ""),
            ("perf: faster", "perf/12-faster", "see the issue"),
            ("test: cover it", "test/3-cover", ""),
            ("revert: undo", "revert/9-undo", ""),
        ]:
            with self.subTest(branch=branch, title=title):
                self.assertTrue(validate_pr(title, branch, body))

    def test_issue_link_accepts_refs_and_cursor_prefix_is_configurable(self):
        self.assertEqual([], validate_pr("fix: save", "fix/18-save", "Resolves #18"))
        self.assertTrue(validate_pr("docs: add guide", "cursor/pr-body-template-01eb", ""))
        self.assertEqual([], validate_pr("docs: add guide", "cursor/pr-body-template-01eb", "", bot_prefixes=("cursor",)))

    def test_body_sections_door_and_author(self):
        self.assertEqual([], validate_body(BODY, "minjunkim-dev"))
        self.assertEqual([], validate_body(BODY.replace("Author: Cursor / grok-4.7", "작성 도구: Cursor 클라우드 에이전트\n작성 모델: grok-4.7")))
        self.assertEqual([], validate_body(BODY.replace("grok-4.7", "없음").replace("Cursor", "사람")))
        self.assertTrue(validate_body(BODY.replace("## Evidence\n", "")))
        self.assertTrue(validate_body(BODY.replace("Door: 되돌리기 쉬움", "Door: 양쪽 문 또는 한쪽 문")))
        self.assertTrue(validate_body(BODY + "Door: 한쪽 문\n"))
        self.assertTrue(validate_body(BODY.replace("Cursor", "Codex")))
        self.assertTrue(validate_body(BODY.replace("사람", "Cursor").replace("grok-4.7", "없음").replace("Cursor / 없음", "사람 / grok-4.7")))
        self.assertTrue(any("disagree" in error for error in validate_body(BODY + "작성 도구: Claude Code\n작성 모델: opus-5.5\n")))
        self.assertEqual(parse_author("Author: Claude Code / Opus 5.5\n이전 작성 모델: grok-4.7, composer-2.5\n")[1], ["grok-4.7", "composer-2.5"])

    def test_door_accepts_current_and_deprecated_values_only(self):
        current = "Door: 되돌리기 쉬움"
        for value in ("되돌리기 쉬움", "되돌리기 어려움", "양쪽 문", "한쪽 문"):
            with self.subTest(value=value):
                self.assertEqual([], validate_body(BODY.replace(current, f"Door: {value}")))
        for value in ("one-way", "two-way", "한쪽문", "되돌리기 어려움 추가", "어려움", ""):
            with self.subTest(value=value):
                errors = validate_body(BODY.replace(current, f"Door: {value}"))
                self.assertTrue(any("되돌리기 쉬움" in error and "되돌리기 어려움" in error for error in errors))
        renamed = BODY.replace(current, "분류: 되돌리기 어려움")
        self.assertTrue(any("Door must be" in error for error in validate_body(renamed)))

    def test_both_checks_use_the_one_author_parser(self):
        import check_review_status as review
        import pr_author
        self.assertIs(workflow_policy.parse_author, pr_author.parse_author)
        self.assertIs(review.parse_author, pr_author.parse_author)
        disagreed = "Author: Claude Code / Opus 5.5\n작성 도구: Cursor\n작성 모델: grok-4.7\n"
        self.assertTrue(any("disagree" in error for error in parse_author(disagreed)[2]))
        model_only = "Author: Cursor / grok-4.7\n작성 모델: Opus 5.5\n"
        self.assertTrue(any("disagree" in error for error in parse_author(model_only)[2]))
        duplicate_model = "Author: Cursor / grok-4.7\n작성 모델: grok-4.7\n작성 모델: Opus 5.5\n"
        self.assertTrue(any("disagree" in error for error in parse_author(duplicate_model)[2]))
        self.assertEqual([], parse_author("Author: Cursor / grok-4.7\n작성 도구: Cursor\n")[2])
        conflict = "Author: Cursor / grok-4.7\nAuthor: Claude Code / Opus 5.5\n"
        self.assertIsNone(parse_author(conflict)[0])
        self.assertTrue(any("conflicts" in error for error in parse_author(conflict)[2]))
        previous = parse_author("Author: Cursor / grok-4.7\n이전 작성 모델: Sonnet 5.5\n이전 작성 모델: Composer 2.5\n")[1]
        self.assertEqual(previous, ["Sonnet 5.5", "Composer 2.5"])

    def test_dependabot_skips_body_rules_and_shell_text_is_not_run(self):
        marker = "/tmp/workflow-policy-body-was-executed"
        if os.path.exists(marker):
            os.unlink(marker)
        payload = "Author: $(touch " + marker + ")\n## Summary\n"
        self.assertEqual([], validate_body(payload, "dependabot[bot]"))
        self.assertFalse(os.path.exists(marker))
        self.assertTrue(validate_body(payload, "minjunkim-dev"))
        self.assertFalse(os.path.exists(marker))

    def test_event_path_checks_the_pull_request_without_running_the_body(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        github = root / ".github"
        github.mkdir()
        (github / "workflow-policy.json").write_text(json.dumps({
            "require_agents_md": False,
            "reject_claude_md": False,
            "feature_flags": False,
            "bot_branch_prefixes": ["claude", "codex", "dependabot", "cursor"],
        }))
        event = root / "event.json"
        event.write_text(json.dumps({"pull_request": {
            "title": "ci: 본문을 검사한다",
            "body": BODY + "\n`os.system('echo no')`\n",
            "head": {"ref": "cursor/pr-convention-checks-01eb"},
            "user": {"login": "minjunkim-dev"},
        }}))
        with patch.object(workflow_policy, "ROOT", root), patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event)}):
            self.assertEqual(0, workflow_policy.main(["--pr"]))
        broken = json.loads(event.read_text())
        broken["pull_request"]["title"] = "feat: add split"
        broken["pull_request"]["body"] = BODY
        event.write_text(json.dumps(broken))
        with patch.object(workflow_policy, "ROOT", root), patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event)}):
            self.assertEqual(1, workflow_policy.main(["--pr"]))

    def test_root_rejects_absolute_and_parent_paths(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        rejected = ("", "/etc", "/var/tmp", "../outside", "policy-head/../../etc", "foo/../../../tmp")
        for value in rejected:
            with self.subTest(value=value):
                buf = StringIO()
                with patch.object(workflow_policy, "ROOT", root), patch("sys.stdout", buf):
                    code = workflow_policy.main(["--root", value])
                self.assertEqual(1, code)
                self.assertIn("root must be a relative path", buf.getvalue())
        nested = root / "nested"
        (nested / "config").mkdir(parents=True)
        (nested / "AGENTS.md").write_text("nested\n", encoding="utf-8")
        (nested / "config" / "feature-flags.json").write_text('{"version": 1, "flags": []}\n', encoding="utf-8")
        previous = Path.cwd()
        try:
            os.chdir(root)
            buf = StringIO()
            with patch.object(workflow_policy, "ROOT", root), patch("sys.stdout", buf):
                code = workflow_policy.main(["--root", "nested"])
            self.assertEqual(0, code, buf.getvalue())
            self.assertIn("PASS", buf.getvalue())
        finally:
            os.chdir(previous)

    def test_template_has_the_sections_and_axes(self):
        text = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
        for header in ("## Summary", "## Evidence", "## Merge Danger", "Author:", "Door:"):
            self.assertIn(header, text)
        for axis in ("Standards", "Spec", "버그 찾기", "Security"):
            self.assertIn(f"| {axis} |", text)
        self.assertIn("axis | model | effort | head SHA | P0 | P1 | P2 | result", text)

    def test_a_pull_request_cannot_replace_the_convention_script(self):
        source = Path(__file__).resolve().parents[1]
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name) / "base"
        pull = Path(temporary.name) / "pull"
        for tree in (base, pull):
            (tree / "scripts").mkdir(parents=True)
            (tree / ".github").mkdir()
        for name in ("workflow_policy.py", "pr_author.py"):
            (base / "scripts" / name).write_text((source / "scripts" / name).read_text(encoding="utf-8"), encoding="utf-8")
        config = source / ".github" / "workflow-policy.json"
        if config.is_file():
            (base / ".github" / "workflow-policy.json").write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
        (pull / "scripts" / "workflow_policy.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        event = Path(temporary.name) / "event.json"
        event.write_text(json.dumps({"pull_request": {
            "title": "Not conventional",
            "body": "",
            "head": {"ref": "evil"},
            "user": {"login": "alice"},
        }}), encoding="utf-8")
        env = os.environ.copy()
        env["GITHUB_EVENT_PATH"] = str(event)
        command = [sys.executable, "scripts/workflow_policy.py", "--pr"]
        # The job's checkout is the base tree, then this relative command. The pull tree's stub would pass.
        blocked = subprocess.run(command, cwd=base, env=env, capture_output=True, text=True, timeout=30)
        bypass = subprocess.run(command, cwd=pull, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, bypass.returncode, bypass.stdout + bypass.stderr)
        self.assertEqual(1, blocked.returncode, blocked.stdout + blocked.stderr)
        self.assertIn("PR title", blocked.stdout)

    def test_base_checker_reads_the_pull_request_tree(self):
        source = Path(__file__).resolve().parents[1]
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        work = Path(temporary.name)
        base = work / "policy-base"
        pull = work / "policy-head"
        for name in ("workflow_policy.py", "pr_author.py"):
            (base / "scripts").mkdir(parents=True, exist_ok=True)
            (base / "scripts" / name).write_text((source / "scripts" / name).read_text(encoding="utf-8"), encoding="utf-8")
        (base / "AGENTS.md").write_text("base copy\n", encoding="utf-8")
        (base / "config").mkdir()
        (base / "config" / "feature-flags.json").write_text('{"version": 1, "flags": []}\n', encoding="utf-8")
        (pull / "scripts").mkdir(parents=True)
        (pull / "scripts" / "workflow_policy.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        (pull / "config").mkdir()
        (pull / "config" / "feature-flags.json").write_text('{"version": 1, "flags": [null]}\n', encoding="utf-8")
        event = work / "event.json"
        event.write_text(json.dumps({"pull_request": {
            "title": "docs: 안내를 고친다",
            "body": BODY,
            "head": {"ref": "docs/notes"},
            "user": {"login": "alice"},
        }}), encoding="utf-8")
        env = os.environ.copy()
        env["GITHUB_EVENT_PATH"] = str(event)
        command = [sys.executable, "policy-base/scripts/workflow_policy.py", "--pr", "--root", "policy-head"]
        missing = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(1, missing.returncode, missing.stdout + missing.stderr)
        self.assertIn("AGENTS.md is required", missing.stdout)
        self.assertIn("Feature flag", missing.stdout)
        (pull / "AGENTS.md").write_text("pull copy\n", encoding="utf-8")
        bad_flags = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(1, bad_flags.returncode, bad_flags.stdout + bad_flags.stderr)
        self.assertNotIn("AGENTS.md is required", bad_flags.stdout)
        self.assertIn("Feature flag", bad_flags.stdout)
        (pull / "config" / "feature-flags.json").write_text('{"version": 1, "flags": []}\n', encoding="utf-8")
        ok = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, ok.returncode, ok.stdout + ok.stderr)
        stub = subprocess.run([sys.executable, "policy-head/scripts/workflow_policy.py"], cwd=work, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, stub.returncode, stub.stdout + stub.stderr)
        (pull / "CLAUDE.md").write_text("not used\n", encoding="utf-8")
        claude = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(1, claude.returncode, claude.stdout + claude.stderr)
        self.assertIn("remove CLAUDE.md", claude.stdout)
        (pull / "CLAUDE.md").unlink()
        (pull / "AGENTS.md").unlink()
        (pull / ".github").mkdir()
        (pull / ".github" / "workflow-policy.json").write_text(
            '{"require_agents_md": false, "reject_claude_md": false, "feature_flags": false, "bot_branch_prefixes": ["dependabot"]}\n',
            encoding="utf-8")
        ignored = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(1, ignored.returncode, ignored.stdout + ignored.stderr)
        self.assertIn("AGENTS.md is required", ignored.stdout)
        (pull / "AGENTS.md").symlink_to("../policy-base/AGENTS.md")
        linked = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(1, linked.returncode, linked.stdout + linked.stderr)
        self.assertIn("AGENTS.md is required", linked.stdout)


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


if __name__ == "__main__":
    unittest.main()

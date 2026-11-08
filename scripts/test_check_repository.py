"""Exercise line-ending detection for files outside the text suffix list."""

from datetime import date
from pathlib import Path
import subprocess
import tempfile
import unittest

from check_repository import ROOT, codeql_source_drift, crlf_paths, validate_flags


class CrlfPathsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.git("init", "-q")
        (self.root / ".gitattributes").write_bytes(b"* text=auto eol=lf\n*.pdf binary\n")
        self.git("add", ".gitattributes")

    def git(self, *args, stdin=None):
        return subprocess.run(["git", *args], cwd=self.root, check=True, input=stdin,
                              stdout=subprocess.PIPE).stdout.decode().strip()

    def stage_raw(self, name, data):
        # Store bytes as-is, like a bot commit created through the GitHub API.
        (self.root / name).write_bytes(data)
        blob = self.git("hash-object", "-w", "--no-filters", "--stdin", stdin=data)
        self.git("update-index", "--add", "--cacheinfo", f"100644,{blob},{name}")

    def test_reports_crlf_in_index_for_unlisted_suffix(self):
        self.stage_raw("gradlew.bat", b"@rem one\r\n@rem two\r\n")
        self.stage_raw("gradlew", b"#!/bin/sh\n")
        self.assertEqual(crlf_paths(self.root), ["gradlew.bat"])

    def test_reports_untracked_crlf_and_ignores_lf_and_binary(self):
        (self.root / "notes.txt").write_bytes(b"a\r\nb\n")
        (self.root / "ok.txt").write_bytes(b"a\nb\n")
        (self.root / "fixture.pdf").write_bytes(b"%PDF\r\n")
        self.assertEqual(crlf_paths(self.root), ["notes.txt"])


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


class CodeqlSourceTest(unittest.TestCase):
    def test_pinned_blob_and_one_action_commit(self):
        self.assertEqual([], codeql_source_drift(ROOT))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".github/workflows").mkdir(parents=True)
            settings = (ROOT / ".github/repository-settings.json").read_text(encoding="utf-8")
            (root / ".github/repository-settings.json").write_text(settings, encoding="utf-8")
            (root / ".github/workflows/codeql.yml").write_text(
                "- uses: github/codeql-action/init@" + "a" * 40 + "\n- uses: github/codeql-action/analyze@" + "b" * 40 + "\n",
                encoding="utf-8")
            self.assertEqual(2, len(codeql_source_drift(root)))


if __name__ == "__main__":
    unittest.main()

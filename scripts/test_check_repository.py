"""Exercise line-ending detection for files outside the text suffix list."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from check_repository import crlf_paths


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


if __name__ == "__main__":
    unittest.main()

import os
from pathlib import Path
import re
import select
import shutil
import stat
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parent / "prepare_beta_accounts.sh"
CONFIG = Path("apps/ios/Config/Local.Release.xcconfig")
KEY = "SMALLNEXT_PRIVACY_POLICY_URL"
SCHEME = "https:/$()/"
# Banner, then stages 1-4 answered as already done.
DONE_THROUGH_ANTHROPIC = ["", "y", "", "y", "", "y", "", "y", ""]


class BetaAccountsWizardTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "scripts").mkdir()
        (self.root / CONFIG.parent).mkdir(parents=True)
        shutil.copy(SCRIPT, self.root / "scripts")
        (self.root / "scripts/prepare_production.py").write_text("raise SystemExit(1)\n")
        stubs = self.root / "stubs"
        stubs.mkdir()
        # Keep open_url from launching a real browser on a developer machine, WSL included.
        for name in ("wslview", "explorer.exe", "xdg-open", "open"):
            (stubs / name).write_text("#!/bin/sh\nexit 0\n")
            (stubs / name).chmod(0o755)
        self.env = {"PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', os.defpath)}",
                    "TERM": "xterm", "HOME": str(self.root), "LANG": "C.UTF-8"}
        self.config = self.root / CONFIG

    def run_wizard(self, answers):
        primary, secondary = os.openpty()
        try:
            process = subprocess.Popen(["bash", str(self.root / "scripts/prepare_beta_accounts.sh")],
                                       stdin=secondary, stdout=secondary, stderr=secondary,
                                       env=self.env, cwd=self.root, close_fds=True)
        except BaseException:
            os.close(primary)
            raise
        finally:
            os.close(secondary)
        os.write(primary, ("\n".join(answers) + "\n").encode())
        output = b""
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([primary], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(primary, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                elif process.poll() is not None:
                    break
            else:
                self.fail("wizard waited for more input than the test provided")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            os.close(primary)
        return process.returncode, output

    def leftovers(self):
        return sorted(path.name for path in self.config.parent.iterdir() if path.name != CONFIG.name)

    def test_refuses_non_terminal_input(self):
        result = subprocess.run(["bash", str(self.root / "scripts/prepare_beta_accounts.sh")],
                                stdin=subprocess.DEVNULL, capture_output=True, env=self.env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL".encode(), result.stdout)

    def test_keeps_spaced_saved_host_and_other_lines(self):
        self.config.write_text(f"A = 1\n{KEY} = {SCHEME}old.example.com/privacy/\n")
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["y", "", "y", "", "n"])
        self.assertEqual(code, 0, output)
        self.assertIn("old.example.com".encode(), output)
        self.assertEqual(self.config.read_text(), f"A = 1\n{KEY}={SCHEME}old.example.com/privacy/\n")
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        self.assertEqual(self.leftovers(), [])

    def test_unsafe_saved_value_is_neither_echoed_nor_reused(self):
        self.config.write_bytes(f"{KEY}={SCHEME}evil.test/x\x1b]0;pwn\x07/privacy/\nB = 2\n".encode())
        answers = DONE_THROUGH_ANTHROPIC + ["y", "https://bad.example/", "API.Example.com", "", "y", "", "n"]
        code, output = self.run_wizard(answers)
        self.assertEqual(code, 0, output)
        self.assertNotIn(b"\x1b]0;pwn", output)
        self.assertEqual(self.config.read_text(), f"B = 2\n{KEY}={SCHEME}api.example.com/privacy/\n")

    def test_conditional_assignment_is_replaced_or_reported(self):
        conditional = f"{KEY}[config=Release] = {SCHEME}old.example.com/privacy/\n"
        self.config.write_text(f"A = 1\n{KEY} = {SCHEME}plain.example.com/privacy/\n{conditional}")
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["y", "new.example.com", "", "y", "", "n"])
        self.assertEqual(code, 0, output)
        self.assertNotIn(b"plain.example.com", output)
        self.assertEqual(self.config.read_text(), f"A = 1\n{KEY}={SCHEME}new.example.com/privacy/\n")
        self.config.write_text(conditional)
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["n", "", "", "n"])
        self.assertEqual(code, 0, output)
        self.assertIn(f"기존 {KEY} 줄 확인 또는 삭제".encode(), output)

    def test_preserves_lines_with_invalid_text_bytes(self):
        self.config.write_bytes(b"BAD = \xff\xfe\nNUL = a\x00b\n")
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["y", "new.example.com", "", "y", "", "n"])
        self.assertEqual(code, 0, output)
        self.assertEqual(self.config.read_bytes(),
                         b"BAD = \xff\xfe\nNUL = a\x00b\n" + f"{KEY}={SCHEME}new.example.com/privacy/\n".encode())

    def test_variables_before_non_ascii_text_are_braced(self):
        # macOS bash 3.2 reads a following UTF-8 lead byte as part of the name and stops under set -u.
        unbraced = re.compile(rb"\$[A-Za-z_][A-Za-z0-9_]*[\x80-\xff]")
        lines = SCRIPT.read_bytes().splitlines()
        self.assertEqual([n for n, line in enumerate(lines, 1) if unbraced.search(line)], [])

    def test_refuses_symlinked_target(self):
        real = self.root / "real.xcconfig"
        real.write_text("X = 1\n")
        self.config.symlink_to(real)
        code, output = self.run_wizard([""])
        self.assertEqual(code, 1, output)
        self.assertIn("symlink".encode(), output)
        self.assertEqual(real.read_text(), "X = 1\n")
        self.assertEqual(self.leftovers(), [])

    def test_refuses_target_that_is_not_a_regular_file(self):
        self.config.mkdir()
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["y", "new.example.com"])
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL".encode(), output)
        self.assertEqual(list(self.config.iterdir()), [])
        self.assertEqual(self.leftovers(), [])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write a read-only file")
    def test_refuses_read_only_target_without_leaving_temp_files(self):
        original = "X = 1\n"
        self.config.write_text(original)
        self.config.chmod(0o444)
        self.addCleanup(self.config.chmod, 0o600)
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["y", "new.example.com"])
        self.assertEqual(code, 1, output)
        self.assertIn("FAIL".encode(), output)
        self.assertEqual(self.config.read_text(), original)
        self.assertEqual(self.leftovers(), [])

    def test_reports_rejected_line_left_in_release_config(self):
        original = f"{KEY}={SCHEME}old.example.com/privacy/\n"
        self.config.write_text(original)
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["n", "n", "", "", "n"])
        self.assertEqual(code, 0, output)
        self.assertIn(f"기존 {KEY} 줄 확인 또는 삭제".encode(), output)
        self.assertEqual(self.config.read_text(), original)

    def test_empty_example_assignment_is_not_reported_as_left_over(self):
        for content in (f"{KEY} =\n", "OTHER = 1\n"):
            with self.subTest(content=content):
                self.config.write_text(content)
                code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["n", "", "", "n"])
                self.assertEqual(code, 0, output)
                self.assertNotIn(f"기존 {KEY} 줄".encode(), output)
                self.assertEqual(self.config.read_text(), content)

    def test_empty_host_answer_skips_the_domain(self):
        original = f"{KEY}={SCHEME}old.example.com/privacy/\n"
        self.config.write_text(original)
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["n", "y", "", "", "", "n"])
        self.assertEqual(code, 0, output)
        self.assertIn("도메인 구매와 Turnstile 위젯".encode(), output)
        self.assertIn(f"기존 {KEY} 줄 확인 또는 삭제".encode(), output)
        self.assertEqual(self.config.read_text(), original)

    def test_lists_failed_server_wizard_as_remaining_work(self):
        code, output = self.run_wizard(DONE_THROUGH_ANTHROPIC + ["n", "", "", "y", "y", ""])
        self.assertEqual(code, 0, output)
        self.assertIn("서버·DNS·DB 준비가 중단됨".encode(), output)


if __name__ == "__main__":
    unittest.main()

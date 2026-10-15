import contextlib
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import prepare_production as wizard


class PreparationTests(unittest.TestCase):
    def values(self):
        return iter([
            "api.example.invalid", "postgres://test:p$a'ss@db.invalid/test",
            "1:123:ios:abcdef", "123", "example-project", "example-client-key",
            "/opt/smallnext/infra/production/credentials", "synthetic-user",
        ])

    def test_private_files_and_hidden_values(self):
        with tempfile.TemporaryDirectory() as directory:
            values = self.values()
            opened = []
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(wizard.prepare(Path(directory), lambda _: next(values), lambda _: "y", opened.append))
            server = Path(directory) / wizard.SERVER_FILE
            ios = Path(directory) / wizard.IOS_FILE
            self.assertEqual(stat.S_IMODE(server.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(ios.stat().st_mode), 0o600)
            self.assertIn("p$a\\'ss", server.read_text())
            self.assertIn("https:/$()/api.example.invalid", ios.read_text())
            self.assertNotIn("USER_SERVER_AI=", server.read_text())
            self.assertNotIn("ANTHROPIC_API_KEY", server.read_text())
            for value in ("p$a'ss", "synthetic-user", "example-client-key"):
                self.assertNotIn(value, output.getvalue())
            self.assertEqual(len(opened), 3)

    def test_declined_overwrite_preserves_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (wizard.SERVER_FILE, wizard.IOS_FILE):
                wizard.save_private(root / name, "original\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(wizard.prepare(root, lambda _: self.fail("must not ask for values"), lambda _: "n"))
            self.assertEqual((root / wizard.SERVER_FILE).read_text(), "original\n")
            self.assertEqual((root / wizard.IOS_FILE).read_text(), "original\n")

    def test_serializers_reject_injected_lines_and_build_expansion(self):
        for value in ("x\nTOKEN=y", "x\r", "x\0"):
            with self.assertRaises(ValueError):
                wizard.env_value(value)
        for value in ("$(OTHER)", "x // comment", "x\nSETTING=y"):
            with self.assertRaises(ValueError):
                wizard.xcconfig_value(value)

    def test_noninteractive_terminal_refuses_before_collecting(self):
        with patch.object(wizard.sys.stdin, "isatty", return_value=False), patch.object(wizard, "prepare") as prepare:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(wizard.main(), 1)
            prepare.assert_not_called()

    def test_confirmed_overwrite_replaces_old_values_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (wizard.SERVER_FILE, wizard.IOS_FILE):
                wizard.save_private(root / name, "original\n")
            values = self.values()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(wizard.prepare(root, lambda _: next(values), lambda _: "y", lambda _: None))
            for name in (wizard.SERVER_FILE, wizard.IOS_FILE):
                self.assertNotIn("original", (root / name).read_text())
                self.assertEqual(stat.S_IMODE((root / name).stat().st_mode), 0o600)

    def test_symlink_does_not_overwrite_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("preserve")
            link = root / wizard.SERVER_FILE
            link.parent.mkdir(parents=True)
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                wizard.prepare(root)
            self.assertEqual(target.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()

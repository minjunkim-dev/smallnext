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
            "api.example.invalid", "postgres://runtime:p$a'ss@db.invalid/test",
            "postgres://schema_owner:migration-only@db.invalid/test",
            "https://example-project.supabase.co", "sb_publishable_synthetic", "synthetic-user",
        ])

    def test_private_files_and_hidden_values(self):
        with tempfile.TemporaryDirectory() as directory:
            values = self.values()
            opened = []
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(wizard.prepare(Path(directory), lambda _: next(values), lambda _: "y", opened.append))
            server = Path(directory) / wizard.SERVER_FILE
            migration = Path(directory) / wizard.MIGRATION_FILE
            ios = Path(directory) / wizard.IOS_FILE
            self.assertEqual(stat.S_IMODE(server.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(migration.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(ios.stat().st_mode), 0o600)
            self.assertIn("p$a\\'ss", server.read_text())
            self.assertIn("schema_owner:migration-only", migration.read_text())
            self.assertNotIn("schema_owner", server.read_text())
            self.assertNotIn("runtime:p", migration.read_text())
            self.assertNotIn("migration-only", output.getvalue())
            self.assertIn("https:/$()/api.example.invalid", ios.read_text())
            self.assertNotIn("USER_SERVER_AI=", server.read_text())
            self.assertNotIn("ANTHROPIC_API_KEY", server.read_text())
            for value in ("p$a'ss", "synthetic-user", "sb_publishable_synthetic"):
                self.assertNotIn(value, output.getvalue())
            self.assertEqual(len(opened), 2)
            self.assertIn("SMALLNEXT_SUPABASE_URL = https:/$()/", ios.read_text())
            self.assertNotIn("FIREBASE", server.read_text())
            self.assertNotIn("SMALLNEXT_FIREBASE", ios.read_text())

    def test_declined_overwrite_preserves_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (wizard.SERVER_FILE, wizard.MIGRATION_FILE, wizard.IOS_FILE):
                wizard.save_private(root / name, "original\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(wizard.prepare(root, lambda _: self.fail("must not ask for values"), lambda _: "n"))
            self.assertEqual((root / wizard.SERVER_FILE).read_text(), "original\n")
            self.assertEqual((root / wizard.MIGRATION_FILE).read_text(), "original\n")
            self.assertEqual((root / wizard.IOS_FILE).read_text(), "original\n")

    def test_serializers_reject_injected_lines_and_build_expansion(self):
        for value in ("x\nTOKEN=y", "x\r", "x\0", "x\\", "x\\'y"):
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
            for name in (wizard.SERVER_FILE, wizard.MIGRATION_FILE, wizard.IOS_FILE):
                wizard.save_private(root / name, "original\n")
            values = self.values()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(wizard.prepare(root, lambda _: next(values), lambda _: "y", lambda _: None))
            self.assertNotIn("original", (root / wizard.SERVER_FILE).read_text())
            for name in (wizard.SERVER_FILE, wizard.MIGRATION_FILE, wizard.IOS_FILE):
                self.assertEqual(stat.S_IMODE((root / name).stat().st_mode), 0o600)

    def test_auth_setup_preserves_optional_crashlytics_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wizard.save_private(root / wizard.IOS_FILE,
                                "SMALLNEXT_FIREBASE_APP_ID = synthetic-crash-app\n"
                                "SMALLNEXT_SUPABASE_URL = old.invalid\n")
            values = self.values()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(wizard.prepare(root, lambda _: next(values), lambda _: "y", lambda _: None))
            text = (root / wizard.IOS_FILE).read_text()
            self.assertIn("SMALLNEXT_FIREBASE_APP_ID = synthetic-crash-app", text)
            self.assertNotIn("old.invalid", text)
            self.assertEqual(text.count("SMALLNEXT_SUPABASE_URL ="), 1)

    def test_release_preparation_leaves_debug_configuration_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            debug = root / "apps/ios/Config/Local.Debug.xcconfig"
            wizard.save_private(debug, "SMALLNEXT_API_BASE_URL = http:/$()/127.0.0.1:8080\n")
            before = debug.read_text()
            values = self.values()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(wizard.prepare(root, lambda _: next(values), lambda _: "y", lambda _: None))
            self.assertEqual(debug.read_text(), before)
            self.assertIn("https:/$()/api.example.invalid", (root / wizard.IOS_FILE).read_text())

    def test_unconfirmed_backup_stops_before_collecting_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            values = iter(["api.example.invalid", "postgres://runtime@db.invalid/test", "postgres://owner@db.invalid/test"])
            answers = iter(["y", "n"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(wizard.prepare(Path(directory), lambda _: next(values), lambda _: next(answers), lambda _: None))
            self.assertFalse((Path(directory) / wizard.SERVER_FILE).exists())
            self.assertFalse((Path(directory) / wizard.MIGRATION_FILE).exists())
            self.assertFalse((Path(directory) / wizard.IOS_FILE).exists())

    def test_secret_or_invalid_client_key_never_reaches_configuration_files(self):
        for client_key in ("sb_secret_synthetic", "legacy-token", "sb_publishable_"):
            with self.subTest(client_key=client_key), tempfile.TemporaryDirectory() as directory:
                values = list(self.values())
                values[4] = client_key
                values = iter(values)
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(ValueError):
                    wizard.prepare(Path(directory), lambda _: next(values), lambda _: "y", lambda _: None)
                self.assertNotIn(client_key, output.getvalue())
                self.assertFalse((Path(directory) / wizard.SERVER_FILE).exists())
                self.assertFalse((Path(directory) / wizard.MIGRATION_FILE).exists())
                self.assertFalse((Path(directory) / wizard.IOS_FILE).exists())

    def test_ai_off_preparation_does_not_require_an_existing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            values = list(self.values())
            values[-1] = ""
            values = iter(values)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(wizard.prepare(Path(directory), lambda _: next(values), lambda _: "y", lambda _: None))
            self.assertIn("AI_ALLOWED_SUPABASE_UIDS=''", (Path(directory) / wizard.SERVER_FILE).read_text())

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

    def test_identical_runtime_and_owner_url_stops_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            values = list(self.values())
            values[2] = values[1]
            values = iter(values)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(ValueError):
                wizard.prepare(Path(directory), lambda _: next(values), lambda _: "y", lambda _: None)
            for name in (wizard.SERVER_FILE, wizard.MIGRATION_FILE, wizard.IOS_FILE):
                self.assertFalse((Path(directory) / name).exists())
            self.assertNotIn("p$a'ss", output.getvalue())

    def test_declined_migration_overwrite_preserves_every_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (wizard.SERVER_FILE, wizard.MIGRATION_FILE, wizard.IOS_FILE):
                wizard.save_private(root / name, "preserved\n")
            answers = iter(["y", "n"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(wizard.prepare(root, lambda _: self.fail("must not collect values"), lambda _: next(answers)))
            for name in (wizard.SERVER_FILE, wizard.MIGRATION_FILE, wizard.IOS_FILE):
                self.assertEqual((root / name).read_text(), "preserved\n")

    def test_migration_symlink_is_rejected_before_collecting_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "preserved"
            target.write_text("original\n")
            path = root / wizard.MIGRATION_FILE
            path.parent.mkdir(parents=True)
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                wizard.prepare(root, lambda _: self.fail("must not collect values"))
            self.assertEqual(target.read_text(), "original\n")


if __name__ == "__main__":
    unittest.main()

"""Exercise rule budgets, scoped coverage, and unwanted context expansion."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_bugbot_rules import MANIFEST, ROOT_RULE, check_rules

REQUIRED = {ROOT_RULE, ".github/.cursor/BUGBOT.md", "docs/.cursor/BUGBOT.md", "scripts/.cursor/BUGBOT.md"}


class BugbotRulesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.manifest({"bugbot_rules": sorted(REQUIRED)})
        for name in REQUIRED:
            self.write(name, "핵심 규칙\n")

    def manifest(self, data):
        path = self.root / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def write(self, name, text, tracked=True):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if tracked:
            subprocess.run(["git", "add", "--", name], cwd=self.root, check=True)

    def test_only_core_and_scoped_rules_count_not_large_detailed_docs(self):
        self.write("docs/detail.md", "x" * 100_001)
        sizes = check_rules(self.root)
        self.assertEqual(set(sizes), REQUIRED)
        self.assertEqual(sizes[ROOT_RULE], len("핵심 규칙\n"))

    def test_individual_boundary_and_one_extra_character(self):
        self.write(ROOT_RULE, "x" * 30_000)
        self.assertEqual(check_rules(self.root)[ROOT_RULE], 30_000)
        self.write(ROOT_RULE, "x" * 30_001)
        with self.assertRaisesRegex(ValueError, "Rule exceeds 30000"):
            check_rules(self.root)

    def test_total_boundary_and_one_extra_character(self):
        remaining = 95_000 - sum(check_rules(self.root).values())
        for i in range(4):
            extra = min(remaining, 30_000)
            self.write(f"area{i}/.cursor/BUGBOT.md", "x" * extra)
            remaining -= extra
        self.assertEqual(remaining, 0)
        self.assertEqual(sum(check_rules(self.root).values()), 95_000)
        self.write(ROOT_RULE, "핵심 규칙\nx")
        with self.assertRaisesRegex(ValueError, "total 95001 exceeds"):
            check_rules(self.root)

    def test_missing_untracked_deleted_empty_and_symlink_rules(self):
        for name in REQUIRED:
            with self.subTest(name=name):
                (self.root / name).unlink()
                with self.assertRaisesRegex(ValueError, "Missing or symlink"):
                    check_rules(self.root)
                self.write(name, "핵심 규칙\n")
        subprocess.run(["git", "rm", "--cached", "--", ROOT_RULE], cwd=self.root,
                       check=True, stdout=subprocess.DEVNULL)
        with self.assertRaisesRegex(ValueError, "Missing tracked"):
            check_rules(self.root)
        self.write(ROOT_RULE, " \n")
        with self.assertRaisesRegex(ValueError, "Empty rule"):
            check_rules(self.root)
        (self.root / ROOT_RULE).unlink()
        self.write("docs/detail.md", "detail")
        (self.root / ROOT_RULE).symlink_to(self.root / "docs/detail.md")
        subprocess.run(["git", "add", "--", ROOT_RULE], cwd=self.root, check=True)
        with self.assertRaisesRegex(ValueError, "Missing or symlink"):
            check_rules(self.root)

    def test_required_rules_come_from_a_valid_manifest(self):
        for data in [None, [], {}, {"bugbot_rules": []}, {"bugbot_rules": ["docs/.cursor/BUGBOT.md"]},
                     {"bugbot_rules": [ROOT_RULE, "docs/notes.md"]}]:
            with self.subTest(data=data):
                self.manifest(data)
                with self.assertRaisesRegex(ValueError, "bugbot_rules must list"):
                    check_rules(self.root)
        (self.root / MANIFEST).unlink()
        with self.assertRaises(OSError):
            check_rules(self.root)

    def test_local_links_cannot_expand_context_or_cross_scopes(self):
        for text in ["[detail](../docs/detail.md)", "[missing](../missing.md)",
                     "[escape](../../outside.md)", "[absolute](/tmp/detail.md)",
                     "[scope](../area/.cursor/BUGBOT.md)",
                     "[multi\nline](../detail(copy).md)",
                     "[outer [inner]](../detail\\(copy\\).md)",
                     "[ref][DETAIL]\n[detail]: <../docs/detail%20name.md#part>",
                     "`[example](../detail.md)`", "```md\n[x](../detail.md)\n```",
                     "<!-- [example](../detail.md) -->"]:
            with self.subTest(text=text):
                self.write(ROOT_RULE, text)
                with self.assertRaisesRegex(ValueError, "Local rule link"):
                    check_rules(self.root)

    def test_example_reference_cannot_shadow_a_visible_local_link(self):
        self.write(ROOT_RULE, "```md\n[x]: https://example.com/example.md\n```\n"
                   "[x]: ../detail.md\n[x]\n")
        with self.assertRaisesRegex(ValueError, "Local rule link"):
            check_rules(self.root)

    def test_nested_rules_checked_without_global_links(self):
        self.write("extra/.cursor/BUGBOT.md", "x" * 30_001)
        with self.assertRaisesRegex(ValueError, "Rule exceeds 30000"):
            check_rules(self.root)
        self.write("extra/.cursor/BUGBOT.md", "[detail](../../detail.md)")
        with self.assertRaisesRegex(ValueError, "Local rule link"):
            check_rules(self.root)

    def test_external_reference_and_fragment_do_not_import_docs(self):
        self.write(ROOT_RULE, "[official](https://cursor.com/docs/bugbot)\n[here](#rules)\n")
        self.assertIn(ROOT_RULE, check_rules(self.root))

    def test_cli_fails_closed_for_unwanted_expansion(self):
        self.write(ROOT_RULE, "[detail](../docs/detail.md)")
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("check_bugbot_rules.py"))],
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Local rule link", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()

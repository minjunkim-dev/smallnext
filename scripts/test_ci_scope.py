#!/usr/bin/env python3
"""Prevent project selection from hiding checks after edits, deletions or moves."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci_scope import scopes


ALL = {"api": True, "container": True, "ios": True, "android": True}


class ScopeTests(unittest.TestCase):
    def selected(self, paths):
        with patch("ci_scope.subprocess.check_output", return_value="\n".join(paths)):
            return scopes({"pull_request": {"base": {"sha": "a" * 40}}})

    def assert_selected(self, paths, *, api=False, container=False, ios=False, android=False):
        self.assertEqual(self.selected(paths), {
            "api": api, "container": container, "ios": ios, "android": android,
        })

    def test_contract_changes_check_all_projects(self):
        self.assertEqual(self.selected(["contracts/openapi.json"]), ALL)

    def test_ios_changes_select_ios(self):
        self.assert_selected(["apps/ios/Sources/ContentView.swift"], ios=True)

    def test_android_changes_select_android(self):
        self.assert_selected(["apps/android/app/src/main/MainActivity.kt"], android=True)

    def test_document_changes_skip_project_builds(self):
        self.assert_selected(["docs/PRODUCT.md", "apps/ios/README.md", "services/api/README.md"])

    def test_container_config_selects_only_container(self):
        self.assert_selected([".dockerignore", ".env.example", "infra/production/compose.yaml"], container=True)

    def test_api_source_selects_checks_and_image(self):
        self.assert_selected(["services/api/src/main.rs"], api=True, container=True)

    def test_api_tests_do_not_rebuild_image(self):
        self.assert_selected(["services/api/tests/database.rs"], api=True)

    def test_rust_toolchain_does_not_select_mobile(self):
        self.assert_selected(["rust-toolchain.toml"], api=True, container=True)

    def test_platform_workflows_select_their_platform(self):
        for workflow, expected in [
            ("api-checks.yml", {"api": True}),
            ("api-container.yml", {"container": True}),
            ("ios-checks.yml", {"ios": True}),
            ("android-checks.yml", {"android": True}),
        ]:
            with self.subTest(workflow=workflow):
                self.assert_selected([".github/workflows/" + workflow], **expected)

    def test_repository_workflow_uses_repository_checks(self):
        self.assert_selected([".github/workflows/repository-checks.yml"])

    def test_orchestrator_and_unknown_workflows_check_all_projects(self):
        for path in [".github/workflows/project-checks.yml", ".github/workflows/new.yml"]:
            with self.subTest(path=path):
                self.assertEqual(self.selected([path]), ALL)

    def test_new_branch_checks_all_projects(self):
        self.assertEqual(scopes({"before": "0" * 40}), ALL)

    def test_unknown_source_checks_all_projects(self):
        self.assertEqual(self.selected(["shared/new-module.rs"]), ALL)

    def test_known_repository_metadata_uses_repository_checks(self):
        self.assert_selected([".gitignore", ".editorconfig", ".github/dependabot.yml"])

    def test_missing_history_checks_all_projects(self):
        with patch("ci_scope.subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            self.assertEqual(scopes({"before": "b" * 40}), ALL)

    def test_real_cross_project_rename_selects_both_projects(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                def git(*args):
                    return subprocess.check_output(
                        ["git", "-c", "user.name=CI Test", "-c", "user.email=ci@example.invalid",
                         "-c", "commit.gpgsign=false", *args], text=True, stderr=subprocess.DEVNULL,
                    ).strip()
                git("init")
                source = Path("apps/ios/example.swift")
                source.parent.mkdir(parents=True)
                source.write_text("example\n")
                git("add", ".")
                git("commit", "-m", "baseline")
                base = git("rev-parse", "HEAD")
                Path("apps/android").mkdir(parents=True)
                git("mv", str(source), "apps/android/example.swift")
                git("commit", "-m", "move across projects")
                self.assertEqual(scopes({"before": base}), {
                    "api": False, "container": False, "ios": True, "android": True,
                })
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()

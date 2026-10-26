#!/usr/bin/env python3
"""Prevent project selection from hiding checks after edits, deletions or moves."""

import io
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci_scope import needs_simulator, scopes


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

    def test_compiled_api_prompts_select_checks_and_image(self):
        for path in ["services/api/src/development_ai/contract.md", "services/api/src/suggestion/generate.md"]:
            with self.subTest(path=path):
                self.assert_selected([path], api=True, container=True)

    def test_api_review_rules_skip_project_builds(self):
        self.assert_selected(["services/api/REVIEW_NOTES.md"])

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

    def test_known_review_and_policy_changes_do_not_build_apps(self):
        paths = [
            ".github/workflows/agent-review.yml", ".github/workflows/pr-policy.yml",
            "scripts/workflow_policy.py", "scripts/test_workflow_policy.py",
            "scripts/review_context.py", "scripts/review_failure.py", "scripts/test_review_failure.py",
            "scripts/review_report.py", "scripts/test_review_report.py",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assert_selected([path])

    def test_unknown_script_still_checks_all_projects(self):
        self.assertEqual(self.selected(["scripts/new-check.py"]), ALL)

    def test_mixed_maintenance_and_app_changes_still_check_the_app(self):
        self.assert_selected(["scripts/review_context.py", "apps/ios/Sources/AppDatabase.swift"], ios=True)

    def test_orchestrator_and_unknown_workflows_check_all_projects(self):
        for path in [".github/workflows/project-checks.yml", ".github/workflows/new.yml"]:
            with self.subTest(path=path):
                self.assertEqual(self.selected([path]), ALL)

    def test_simulator_runs_only_for_app_shell_inputs(self):
        for path in ["apps/ios/Sources/ContentView.swift", "apps/ios/Tests/CrashReportingTests.swift",
                     "apps/ios/Config/Debug.plist", "apps/ios/project.yml",
                     "apps/ios/Smallnext.xcodeproj/project.pbxproj", "config/feature-flags.json",
                     ".ci/toolchains.json", "scripts/check_ios.sh", ".github/workflows/ios-checks.yml"]:
            with self.subTest(path=path):
                self.assertTrue(needs_simulator([path]))
        for path in ["apps/ios/Packages/SmallnextCore/Sources/SmallnextCore/ProgressFlow.swift",
                     "apps/ios/Packages/SmallnextCore/Tests/SmallnextCoreTests/ProgressFlowTests.swift",
                     "docs/CI.md", "services/api/src/main.rs", "apps/android/app/build.gradle.kts"]:
            with self.subTest(path=path):
                self.assertFalse(needs_simulator([path]))

    def test_unknown_history_runs_simulator(self):
        self.assertTrue(needs_simulator(None))

    def test_entry_point_writes_projects_and_simulator_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            event, output = Path(directory) / "event.json", Path(directory) / "output"
            event.write_text('{"before": "' + "b" * 40 + '"}')
            core = "apps/ios/Packages/SmallnextCore/Sources/SmallnextCore/FeatureFlags.swift"
            with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(output)}), \
                 patch("ci_scope.subprocess.check_output", return_value=core), \
                 patch("sys.stdout", new_callable=io.StringIO):
                runpy.run_module("ci_scope", run_name="__main__")
            self.assertEqual(output.read_text().splitlines(), [
                "api=false", "container=false", "ios=true", "android=false", "ios_simulator=false",
            ])

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

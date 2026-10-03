#!/usr/bin/env python3
"""Check that contract and project changes cannot silently skip required jobs."""

import subprocess
import unittest
from unittest.mock import patch

from ci_scope import scopes


class ScopeTests(unittest.TestCase):
    def selected(self, paths):
        with patch("ci_scope.subprocess.check_output", return_value="\n".join(paths)):
            return scopes({"pull_request": {"base": {"sha": "a" * 40}}})

    def test_contract_changes_check_all_projects(self):
        self.assertEqual(self.selected(["contracts/openapi.json"]),
                         {"api": True, "ios": True, "android": True})

    def test_ios_changes_select_ios(self):
        self.assertEqual(self.selected(["apps/ios/Sources/ContentView.swift"]),
                         {"api": False, "ios": True, "android": False})

    def test_document_changes_skip_project_builds(self):
        self.assertEqual(self.selected(["docs/PRODUCT.md"]),
                         {"api": False, "ios": False, "android": False})

    def test_root_container_config_selects_api(self):
        self.assertEqual(self.selected([".dockerignore", ".env.example"]),
                         {"api": True, "ios": False, "android": False})

    def test_new_branch_checks_all_projects(self):
        self.assertEqual(scopes({"before": "0" * 40}),
                         {"api": True, "ios": True, "android": True})

    def test_missing_history_checks_all_projects(self):
        with patch("ci_scope.subprocess.check_output",
                   side_effect=subprocess.CalledProcessError(1, "git")):
            self.assertEqual(scopes({"before": "b" * 40}),
                             {"api": True, "ios": True, "android": True})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

import copy
import unittest

from check_github_settings import audit, differences


class GitHubSettingsTests(unittest.TestCase):
    def test_missing_security_field_is_drift(self):
        self.assertEqual(
            differences({"secret_scanning": {"status": "enabled"}}, {}),
            ["secret_scanning"],
        )

    def test_checks_ignore_order_but_reject_extra_or_duplicate_entries(self):
        expected = [{"context": "CI", "app_id": 15368}, {"context": "policy", "app_id": 15368}]
        self.assertEqual(differences(expected, list(reversed(expected)), "checks"), [])
        self.assertEqual(differences(expected, expected + [expected[0]], "checks"), ["checks"])

    def test_wrong_check_app_and_boolean_types_are_not_accepted(self):
        self.assertEqual(differences([{"context": "CI", "app_id": 15368}],
                                     [{"context": "CI", "app_id": 1}], "checks"), ["checks"])
        self.assertEqual(differences(True, 1, "enabled"), ["enabled"])

    def profile(self):
        return {
            "schema_version": 1, "repository": "owner/repo", "repository_id": 12,
            "default_branch": "main",
            "expected": {"repository": {"allow_merge_commit": False},
                         "dependabot_alerts": {"enabled": True}},
        }

    def test_live_reader_receives_only_get_paths_and_detects_drift(self):
        calls = []
        def read(path):
            calls.append(path)
            return {"id": 12, "full_name": "owner/repo", "allow_merge_commit": True} if len(calls) == 1 else None
        self.assertEqual(audit(self.profile(), read), ["repository.allow_merge_commit"])
        self.assertEqual(calls, ["repos/owner/repo", "repos/owner/repo/vulnerability-alerts"])

    def test_wrong_repository_and_request_paths_stop_before_extra_reads(self):
        for value in ["owner/repo?bad", "../repo", "https://github.com/owner/repo"]:
            profile = self.profile()
            profile["repository"] = value
            with self.assertRaises(ValueError):
                audit(profile, lambda _: self.fail("Invalid repository reached the API"))
        with self.assertRaises(ValueError):
            audit(self.profile(), lambda _: {"id": 13, "full_name": "owner/repo"})

    def test_permission_failure_is_unverified_not_disabled_or_pass(self):
        def read(path):
            if path.endswith("vulnerability-alerts"):
                raise PermissionError("no access")
            return {"id": 12, "full_name": "owner/repo", "allow_merge_commit": False}
        with self.assertRaises(PermissionError):
            audit(self.profile(), read)

    def test_unknown_endpoint_is_rejected(self):
        profile = copy.deepcopy(self.profile())
        profile["expected"]["secrets"] = {}
        def read(path):
            return {"id": 12, "full_name": "owner/repo", "allow_merge_commit": False}
        with self.assertRaises(ValueError):
            audit(profile, read)


if __name__ == "__main__":
    unittest.main()

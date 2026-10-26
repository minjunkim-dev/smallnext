#!/usr/bin/env python3

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_github_settings as settings
import unittest

from check_github_settings import audit, codeql_source_drift, differences

# Synthetic default-setup profile: unit tests must not depend on a consumer checkout.
BASELINE = {
    "schema_version": 1, "repository": "owner/repo", "repository_id": 12, "default_branch": "main",
    "expected": {
        "repository": {
            "default_branch": "main", "visibility": "private", "allow_merge_commit": False,
            "allow_rebase_merge": False, "allow_squash_merge": True, "allow_auto_merge": False,
            "delete_branch_on_merge": True, "allow_update_branch": True,
            "squash_merge_commit_title": "PR_TITLE", "squash_merge_commit_message": "PR_BODY",
            "security_and_analysis": {
                name: {"status": "enabled"} for name in
                ("dependabot_security_updates", "secret_scanning", "secret_scanning_push_protection")
            },
        },
        "protection": {
            "required_status_checks": {"strict": True, "checks": [{"context": "CI", "app_id": 15368}]},
            "required_pull_request_reviews": {
                "required_approving_review_count": 0, "dismiss_stale_reviews": True,
                "require_code_owner_reviews": False, "require_last_push_approval": False,
            },
            **{name: {"enabled": enabled} for name, enabled in {
                "enforce_admins": True, "required_linear_history": True,
                "required_conversation_resolution": True, "allow_force_pushes": False,
                "allow_deletions": False, "lock_branch": False,
            }.items()},
        },
        "rulesets": [], "actions": {"enabled": True, "allowed_actions": "selected", "sha_pinning_required": True},
        "allowed_actions": {"github_owned_allowed": True, "verified_allowed": False, "patterns_allowed": []},
        "workflow_token": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
        "fork_policy": {"approval_policy": "all_external_contributors"},
        "immutable_releases": {"enabled": True}, "dependabot_alerts": {"enabled": True},
        "codeql": {"state": "configured"},
    },
}


def advanced(profile):
    """The project's profile as an advanced CodeQL setup, whatever setup the project uses."""
    profile = copy.deepcopy(profile)
    workflow = ".github/workflows/codeql.yml"
    profile["expected"]["codeql"] = {"state": "not-configured"}
    profile["expected"].setdefault("codeql_workflow", {"path": workflow, "state": "active"})
    profile["expected"].setdefault("codeql_main_source", {"path": workflow, "type": "file", "sha": "0" * 40})
    return profile


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

    def test_baseline_pins_checked_out_codeql_workflow(self):
        profile = advanced(BASELINE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / profile["expected"]["codeql_main_source"]["path"]
            workflow.parent.mkdir(parents=True)
            data = ("steps:\n  - uses: github/codeql-action/analyze@" + "a" * 40 + "\n").encode()
            workflow.write_bytes(data)
            profile["expected"]["codeql_main_source"]["sha"] = settings.hashlib.sha1(
                b"blob %d\0" % len(data) + data).hexdigest()
            with patch.object(settings, "ROOT", root):
                self.assertEqual(codeql_source_drift(profile), [])
                profile["expected"]["codeql_main_source"]["sha"] = "0" * 40
                self.assertEqual(codeql_source_drift(profile), ["codeql_main_source.sha"])
        # Installed copies additionally check the consumer's real profile and workflow pin.
        path = settings.ROOT / ".github/repository-settings.json"
        if path.exists():
            project = json.loads(path.read_text())
            settings.validate_profile(project)
            self.assertEqual(codeql_source_drift(project), [])

    def test_codeql_action_steps_must_share_one_commit(self):
        # Split Dependabot PRs bumped init without analyze; every analyze job failed.
        a, b = "a" * 40, "b" * 40
        mismatch = ["codeql_workflow.action_pins"]
        cases = [
            (f"      - uses: github/codeql-action/analyze@{a} # v4\n", []),
            (f"      - uses: 'github/codeql-action/analyze@{a.upper()}'\n", []),
            (f"      - name: Analyze\n        \"uses\": github/codeql-action/analyze@{a}\n", []),
            (f"      # was github/codeql-action/analyze@{b}\n      - uses: github/codeql-action/analyze@{a}\n", []),
            (f"      - run: |\n          - uses: github/codeql-action/analyze@{b}\n", []),
            # Inputs are not parsed apart from steps; a mismatched ref anywhere fails closed.
            (f"      - uses: actions/x@{a}\n        with:\n          uses: github/codeql-action/analyze@{b}\n", mismatch),
            (f"      - uses: github/codeql-action/analyze@{b} # v4\n", mismatch),
            ("      - uses: github/codeql-action/analyze@v4\n", mismatch),
            ("      - uses: >-\n          github/codeql-action/analyze@v4\n", mismatch),
            ("      - {uses: github/codeql-action/analyze@v4}\n", mismatch),
            (f"      -   name: Analyze\n          uses: github/codeql-action/analyze@{b}\n", mismatch),
            (f"      -   name: Analyze\n          uses: github/codeql-action/analyze@{a}\n", []),
            (f"      -\n          uses: github/codeql-action/analyze@{b}\n", mismatch),
            (f"      - {{name: Analyze,\n          uses: github/codeql-action/analyze@{b}}}\n", mismatch),
            ("      - uses: |\n          github/codeql-action/analyze@v4\n", mismatch),
            ("      - name: |-\n          Analyze\n        uses: github/codeql-action/analyze@v4\n", mismatch),
            ("      - {name: \"Analyze #2\", uses: github/codeql-action/analyze@v4}\n", mismatch),
            (f"      - name: \"x: |\"\n        uses: github/codeql-action/analyze@{b}\n", mismatch),
            (f"      - name: \"Analyze #2\"\n        uses: github/codeql-action/analyze@{a}\n", []),
            (f"      - uses: GitHub/CodeQL-Action/analyze@{b}\n", mismatch),
        ]
        with tempfile.TemporaryDirectory() as folder:
            profile = advanced(BASELINE)
            workflow = Path(folder) / profile["expected"]["codeql_main_source"]["path"]
            workflow.parent.mkdir(parents=True)
            for analyze, expected in cases:
                data = (f"jobs:\n  analyze:\n    steps:\n      - uses: github/codeql-action/init@{a} # v4\n"
                        + analyze).encode()
                workflow.write_bytes(data)
                profile["expected"]["codeql_main_source"]["sha"] = settings.hashlib.sha1(
                    b"blob %d\0" % len(data) + data).hexdigest()
                with self.subTest(analyze=analyze), patch.object(settings, "ROOT", Path(folder)):
                    self.assertEqual(codeql_source_drift(profile), expected)

    def test_default_setup_profile_has_no_workflow_controls(self):
        profile = advanced(BASELINE)
        profile["expected"]["codeql"] = {"state": "configured"}
        with self.assertRaisesRegex(ValueError, "every required control"):
            settings.validate_profile(profile)
        for name in settings.ADVANCED_CODEQL:
            del profile["expected"][name]
        settings.validate_profile(profile)
        self.assertEqual(codeql_source_drift(profile), [])

    def profile(self):
        profile = copy.deepcopy(BASELINE)
        profile.update(repository="owner/repo", repository_id=12)
        return profile

    def reader(self, path):
        profile = self.profile()
        if path == "repos/owner/repo":
            return {"id": 12, "full_name": "owner/repo", **profile["expected"]["repository"]}
        if path.endswith("vulnerability-alerts"):
            return None
        endpoints = {
            "branches/main/protection": "protection", "rulesets": "rulesets",
            "actions/permissions": "actions", "actions/permissions/selected-actions": "allowed_actions",
            "actions/permissions/workflow": "workflow_token",
            "actions/permissions/fork-pr-contributor-approval": "fork_policy",
            "immutable-releases": "immutable_releases", "code-scanning/default-setup": "codeql",
            "actions/workflows/codeql.yml": "codeql_workflow",
            "contents/.github/workflows/codeql.yml?ref=main": "codeql_main_source",
        }
        return copy.deepcopy(profile["expected"][endpoints[path.removeprefix("repos/owner/repo/")]])

    def test_live_reader_receives_only_get_paths_and_detects_drift(self):
        calls = []
        def read(path):
            calls.append(path)
            value = self.reader(path)
            if len(calls) == 1:
                value["allow_merge_commit"] = True
            return value
        self.assertEqual(audit(self.profile(), read), ["repository.allow_merge_commit"])
        self.assertEqual(len(calls), len(self.profile()["expected"]))  # metadata + each other control
        self.assertTrue(all(path.startswith("repos/owner/repo") for path in calls))

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
            return self.reader(path)
        with self.assertRaises(PermissionError):
            audit(self.profile(), read)

    def test_unknown_endpoint_is_rejected(self):
        profile = copy.deepcopy(self.profile())
        profile["expected"]["secrets"] = {}
        def read(path):
            return self.reader(path)
        with self.assertRaises(ValueError):
            audit(profile, read)

    def run_main(self, profile, read):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github").mkdir()
            (root / ".github/repository-settings.json").write_text(json.dumps(profile))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(settings, "ROOT", root), patch.object(settings, "read_api", read), redirect_stdout(stdout), redirect_stderr(stderr):
                status = settings.main()
            return status, stdout.getvalue(), stderr.getvalue()

    def test_incomplete_baselines_are_unverified_before_network_access(self):
        for expected in [{}, [], None]:
            profile = self.profile()
            profile["expected"] = expected
            status, out, err = self.run_main(profile, lambda _: self.fail("Incomplete baseline reached network"))
            self.assertEqual(status, 2)
            self.assertEqual(out, "")
            self.assertIn("UNVERIFIED", err)
        for control in self.profile()["expected"]:
            profile = self.profile()
            del profile["expected"][control]
            self.assertEqual(self.run_main(profile, lambda _: self.fail("Missing control reached network"))[0], 2)
        profile = self.profile()
        del profile["expected"]["protection"]["enforce_admins"]["enabled"]
        self.assertEqual(self.run_main(profile, lambda _: self.fail("Missing protection reached network"))[0], 2)

    def test_invalid_data_and_lookup_errors_are_unverified(self):
        profile = self.profile()
        profile["default_branch"] = None
        self.assertEqual(self.run_main(profile, self.reader)[0], 2)
        self.assertEqual(self.run_main(self.profile(), lambda _: None)[0], 2)
        def read(path):
            raise PermissionError("no access")
        status, out, err = self.run_main(self.profile(), read)
        self.assertEqual(status, 2)
        self.assertEqual(out, "")
        self.assertIn("UNVERIFIED", err)

    def test_extra_non_protection_field_reports_drift_without_schema_crash(self):
        profile = self.profile()
        profile["expected"]["repository"]["required_status_checks"] = False
        status, out, err = self.run_main(profile, self.reader)
        self.assertEqual(status, 1)
        self.assertIn("repository.required_status_checks", out)
        self.assertEqual(err, "")

    def exception(self, status="unsupported"):
        return {"status": status, "reason": "Private repository plan lacks this feature",
                "evidence": "GitHub documentation and repository setup review"}

    def test_declared_unsupported_control_is_limited_and_other_drift_still_fails(self):
        profile = self.profile()
        del profile["expected"]["protection"]
        profile["exceptions"] = {"protection": self.exception()}
        def read(path):
            self.assertFalse(path.endswith("/protection"), "Unavailable control must not be queried")
            return self.reader(path)
        status, out, err = self.run_main(profile, read)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("UNSUPPORTED: protection", out)
        self.assertIn("LIMITED:", out)
        self.assertNotIn("PASS:", out)
        profile["expected"]["actions"]["enabled"] = False
        self.assertEqual(self.run_main(profile, read)[0], 1)

    def test_nested_unavailable_fields_and_codeql_language_exception(self):
        profile = advanced(self.profile())
        for name in ("codeql", *settings.ADVANCED_CODEQL):
            del profile["expected"][name]
        del profile["expected"]["repository"]["security_and_analysis"]["secret_scanning"]
        del profile["expected"]["actions"]["sha_pinning_required"]
        profile["exceptions"] = {
            "codeql": self.exception("not_applicable"),
            "repository.security_and_analysis.secret_scanning.status": self.exception(),
            "actions.sha_pinning_required": self.exception(),
        }
        def read(path):
            self.assertNotIn("code-scanning", path)
            self.assertNotIn("codeql.yml", path)
            result = self.reader(path)
            if path == "repos/owner/repo":
                del result["security_and_analysis"]["secret_scanning"]
            elif path.endswith("actions/permissions"):
                del result["sha_pinning_required"]
            return result
        status, out, err = self.run_main(profile, read)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("NOT_APPLICABLE: codeql", out)
        self.assertEqual(codeql_source_drift(profile), [])

    def test_invalid_exceptions_cannot_erase_required_controls(self):
        cases = [None, {"protection": {}}, {"secrets": self.exception()},
                 {"repository.allow_squash_merge": self.exception()},
                 {"protection": self.exception("unverified")},
                 {"protection": self.exception() | {"evidence": " "}},
                 {"protection": self.exception(), "actions": self.exception(),
                  "actions.sha_pinning_required": self.exception()}]
        for exceptions in cases:
            profile = self.profile()
            del profile["expected"]["protection"]
            profile["exceptions"] = exceptions
            with self.subTest(exceptions=exceptions):
                self.assertEqual(self.run_main(profile, lambda _: self.fail("Invalid exception reached API"))[0], 2)
        profile = self.profile()
        profile["exceptions"] = {"protection": self.exception()}
        self.assertEqual(self.run_main(profile, lambda _: self.fail("Conflicting expectation reached API"))[0], 2)

    def test_403_and_404_do_not_automatically_become_availability_exceptions(self):
        for code in (403, 404):
            def read(path):
                if path.endswith("/protection"):
                    raise settings.subprocess.CalledProcessError(1, ["gh", "api"], stderr=f"HTTP {code}")
                return self.reader(path)
            status, out, err = self.run_main(self.profile(), read)
            self.assertEqual((status, out), (2, ""))
            self.assertIn("UNVERIFIED", err)

    def test_main_pass_and_drift_have_distinct_exit_codes(self):
        status, out, err = self.run_main(self.profile(), self.reader)
        self.assertEqual(status, 0)
        self.assertIn("PASS", out)
        self.assertEqual(err, "")
        profile = self.profile()
        profile["expected"]["protection"]["enforce_admins"]["enabled"] = False
        status, out, err = self.run_main(profile, self.reader)
        self.assertEqual(status, 1)
        self.assertIn("protection.enforce_admins.enabled", out)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()

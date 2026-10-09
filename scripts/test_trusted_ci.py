"""Exercise the trusted aggregation boundary with GitHub REST responses."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trusted_ci import aggregate, main


REPO = "minjunkim-dev/smallnext"
HEAD = "a" * 40
BASE = "b" * 40


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.run = {
            "id": 10, "run_attempt": 1, "workflow_id": 20,
            "path": ".github/workflows/project-checks.yml", "event": "pull_request",
            "head_sha": HEAD, "head_branch": "ci/83-example",
            "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO},
            "status": "completed", "conclusion": "success", "pull_requests": [],
        }
        self.event = {"repository": {"full_name": REPO, "default_branch": "main"},
                      "workflow_run": deepcopy(self.run)}
        self.pr = {"number": 30, "state": "open", "changed_files": 1,
                   "head": {"sha": HEAD, "ref": "ci/83-example", "repo": {"full_name": REPO}},
                   "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO}}}
        self.jobs = [self.job(name, result) for name, result in [
            ("scope", "success"), ("Project checks", "success"),
            ("api", "skipped"), ("container", "skipped"),
            ("ios", "skipped"), ("android", "skipped"),
        ]]
        self.data = {
            "actions/workflows/project-checks.yml": {"id": 20, "path": self.run["path"]},
            "actions/runs/10": self.run,
            "pulls?state=open&base=main&per_page=100&page=1": [self.pr],
            "pulls/30": self.pr,
            "pulls/30/files?per_page=100&page=1": [{"filename": "docs/CI.md", "status": "modified"}],
            "branches/main": {"commit": {"sha": BASE}},
            "actions/workflows/20/runs?event=pull_request&branch=ci%2F83-example&head_sha=" + HEAD + "&per_page=1": {"workflow_runs": [self.run]},
            "actions/runs/10/attempts/1/jobs?per_page=100&page=1": {"total_count": 6, "jobs": self.jobs},
        }

    def job(self, name, result):
        return {"id": len(name), "name": name, "run_id": 10, "run_attempt": 1,
                "head_sha": HEAD, "status": "completed", "conclusion": result}

    def get(self, endpoint):
        return deepcopy(self.data[endpoint])

    def test_document_pr_passes_with_actual_skipped_jobs_and_empty_pr_array(self):
        result = aggregate(self.event, REPO, self.get)
        self.assertEqual(result["verdict"], "accepted")
        self.assertEqual((result["pr"], result["run_id"], result["attempt"], result["base_sha"]),
                         (30, 10, 1, BASE))
        self.assertEqual(result["selected"], {"api": False, "container": False, "ios": False, "android": False})

    def select_ios(self):
        self.data["pulls/30/files?per_page=100&page=1"] = [{"filename": "apps/ios/Sources/App.swift"}]
        self.jobs[4] = self.job("ios / test", "success")

    def test_selected_job_failure_cancellation_skipping_or_omission_is_rejected(self):
        self.select_ios()
        for conclusion in ("failure", "cancelled", "skipped", "timed_out", "neutral", None):
            with self.subTest(conclusion=conclusion):
                self.jobs[4]["conclusion"] = conclusion
                with self.assertRaisesRegex(ValueError, "ios / test: expected success"):
                    aggregate(self.event, REPO, self.get)
        self.jobs.pop(4)
        self.data["actions/runs/10/attempts/1/jobs?per_page=100&page=1"]["total_count"] = 5
        with self.assertRaisesRegex(ValueError, "re-run all jobs"):
            aggregate(self.event, REPO, self.get)

    def test_actual_jobs_decide_even_if_pr_supplies_forged_scope_or_gate_input(self):
        self.select_ios()
        self.event["NEEDS_JSON"] = '{"scope":{"result":"success"}}'
        self.event["workflow_run"]["outputs"] = {"ios": "false"}
        self.assertEqual(aggregate(self.event, REPO, self.get)["verdict"], "accepted")
        self.jobs[4] = self.job("ios", "skipped")
        with self.assertRaisesRegex(ValueError, "re-run all jobs"):
            aggregate(self.event, REPO, self.get)

    def test_every_project_and_both_android_jobs_are_required_for_workflow_changes(self):
        self.data["pulls/30/files?per_page=100&page=1"] = [{"filename": ".github/workflows/project-checks.yml"}]
        self.jobs[:] = [self.job(name, "success") for name in (
            "scope", "Project checks", "api / verify", "container / image", "ios / test",
            "android / build", "android / device-tests")]
        self.data["actions/runs/10/attempts/1/jobs?per_page=100&page=1"]["total_count"] = 7
        self.assertTrue(all(aggregate(self.event, REPO, self.get)["selected"].values()))
        self.jobs[-1]["conclusion"] = "failure"
        with self.assertRaisesRegex(ValueError, "android / device-tests"):
            aggregate(self.event, REPO, self.get)

    def test_move_selects_both_old_and_new_projects(self):
        self.data["pulls/30/files?per_page=100&page=1"] = [
            {"filename": "services/api/tests/example.swift", "previous_filename": "apps/ios/Example.swift"}]
        self.jobs[2] = self.job("api / verify", "success")
        self.jobs[4] = self.job("ios / test", "success")
        self.assertEqual(aggregate(self.event, REPO, self.get)["selected"],
                         {"api": True, "container": False, "ios": True, "android": False})

    def test_run_and_job_identities_must_match(self):
        baseline = deepcopy(self.run)
        for key, value in [("workflow_id", 99), ("path", ".github/workflows/other.yml"),
                           ("id", 99), ("head_sha", "c" * 40), ("head_branch", "other"),
                           ("run_attempt", 2), ("event", "push"),
                           ("repository", {"full_name": "other/repo"}), ("status", "in_progress")]:
            with self.subTest(key=key):
                self.data["actions/runs/10"] = dict(baseline, **{key: value})
                with self.assertRaises(ValueError):
                    aggregate(self.event, REPO, self.get)
        self.data["actions/runs/10"] = baseline
        for key, value in [("run_id", 99), ("run_attempt", 2), ("head_sha", "c" * 40),
                           ("status", "in_progress"), ("conclusion", "failure")]:
            with self.subTest(job_key=key):
                self.jobs[0] = dict(self.job("scope", "success"), **{key: value})
                with self.assertRaises(ValueError):
                    aggregate(self.event, REPO, self.get)

    def test_failure_and_cancellation_are_not_merge_evidence(self):
        for result in ("failure", "cancelled"):
            self.run["conclusion"] = result
            with self.assertRaisesRegex(ValueError, "Source run"):
                aggregate(self.event, REPO, self.get)

    def test_stale_or_ambiguous_pr_is_rejected(self):
        self.pr["head"]["sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "Stale head"):
            aggregate(self.event, REPO, self.get)
        self.pr["head"]["sha"] = HEAD
        self.data["pulls?state=open&base=main&per_page=100&page=1"].append(dict(self.pr, number=31))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            aggregate(self.event, REPO, self.get)

    def test_push_fork_and_closed_pr_are_explicitly_out_of_scope(self):
        self.run["event"] = self.event["workflow_run"]["event"] = "push"
        self.assertEqual(aggregate(self.event, REPO, self.get)["verdict"], "out_of_scope")
        self.run["event"] = self.event["workflow_run"]["event"] = "pull_request"
        self.run["head_repository"] = {"full_name": "other/fork"}
        self.assertIn("Fork", aggregate(self.event, REPO, self.get)["reason"])
        self.run["head_repository"] = {"full_name": REPO}
        self.data["pulls?state=open&base=main&per_page=100&page=1"] = []
        self.assertIn("closed or deleted", aggregate(self.event, REPO, self.get)["reason"])

    def test_source_rerun_or_pr_change_during_collection_is_rejected(self):
        for endpoint, mutation in [
            ("actions/runs/10", lambda value: value.update(run_attempt=2)),
            ("pulls/30", lambda value: value["head"].update(sha="c" * 40)),
            ("pulls/30", lambda value: value["base"].update(sha="c" * 40)),
            ("pulls/30", lambda value: value.update(state="closed")),
            ("branches/main", lambda value: value["commit"].update(sha="c" * 40)),
        ]:
            calls = 0
            def changing_get(path):
                nonlocal calls
                value = self.get(path)
                if path == endpoint:
                    calls += 1
                    if calls == 2:
                        mutation(value)
                return value
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    aggregate(self.event, REPO, changing_get)

    def test_newer_run_and_incomplete_diff_or_job_page_are_rejected(self):
        latest = next(key for key in self.data if key.startswith("actions/workflows/20/runs?"))
        self.data[latest] = {"workflow_runs": [{"id": 11}]}
        with self.assertRaisesRegex(ValueError, "newer source run"):
            aggregate(self.event, REPO, self.get)
        self.data[latest] = {"workflow_runs": [self.run]}
        self.pr["changed_files"] = 2
        with self.assertRaisesRegex(ValueError, "Incomplete PR diff"):
            aggregate(self.event, REPO, self.get)
        self.pr["changed_files"] = 1
        self.data["actions/runs/10/attempts/1/jobs?per_page=100&page=1"]["total_count"] = 7
        with self.assertRaisesRegex(ValueError, "Incomplete API list"):
            aggregate(self.event, REPO, self.get)

    def test_partial_attempt_never_reuses_previous_attempt_jobs(self):
        self.run["run_attempt"] = self.event["workflow_run"]["run_attempt"] = 2
        self.data["actions/runs/10/attempts/2/jobs?per_page=100&page=1"] = {
            "total_count": 1, "jobs": [dict(self.job("Project checks", "success"), run_attempt=2)]}
        with self.assertRaisesRegex(ValueError, "re-run all jobs"):
            aggregate(self.event, REPO, self.get)

    def test_api_failure_is_reported_as_rejected_with_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            summary = Path(directory) / "summary.md"
            event.write_text(json.dumps(self.event))
            env = {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REPOSITORY": REPO,
                   "GITHUB_EVENT_PATH": str(event), "GITHUB_STEP_SUMMARY": str(summary),
                   "GITHUB_RUN_ID": "40", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": BASE}
            with patch.dict(os.environ, env), patch("trusted_ci.api_get", side_effect=OSError("API unavailable")), patch("builtins.print"):
                self.assertEqual(main(), 1)
            report = summary.read_text()
            self.assertIn('"verdict": "rejected"', report)
            self.assertIn("API unavailable", report)


    def test_unknown_or_unselected_success_jobs_and_duplicate_names_are_rejected(self):
        baseline = deepcopy(self.jobs)
        for jobs in [baseline + [baseline[0]], baseline + [self.job("unknown", "success")],
                     baseline[:2] + [self.job("api", "success")] + baseline[3:]]:
            self.jobs[:] = jobs
            self.data["actions/runs/10/attempts/1/jobs?per_page=100&page=1"]["total_count"] = len(jobs)
            with self.assertRaises(ValueError):
                aggregate(self.event, REPO, self.get)

    def test_complete_diff_and_open_pr_pagination(self):
        self.pr["changed_files"] = 101
        self.data["pulls/30/files?per_page=100&page=1"] = [{"filename": f"docs/{n}.md"} for n in range(100)]
        self.data["pulls/30/files?per_page=100&page=2"] = [{"filename": "apps/ios/Sources/App.swift"}]
        self.jobs[4] = self.job("ios / test", "success")
        self.data["pulls?state=open&base=main&per_page=100&page=1"] = [
            {"head": {"repo": {"full_name": "other/fork"}, "ref": "other"}} for _ in range(100)]
        self.data["pulls?state=open&base=main&per_page=100&page=2"] = [self.pr]
        self.assertTrue(aggregate(self.event, REPO, self.get)["selected"]["ios"])


class WorkflowTests(unittest.TestCase):
    def test_workflow_uses_default_sha_and_only_read_permissions_without_pr_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/trusted-aggregation.yml").read_text()
        self.assertIn("types: [completed]", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertNotIn("write", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("download-artifact", workflow)
        self.assertNotIn("workflow_run.head_sha", workflow)


if __name__ == "__main__":
    unittest.main()

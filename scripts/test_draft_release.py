from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from draft_release import ASSETS, REPO, check_ci, digest, inputs, preflight, publish, verify

SOURCE = "a" * 40
VERSION = "v0.1.0-alpha.20261014"


class DraftReleaseTest(unittest.TestCase):
    def setUp(self):
        self.runs = {}
        self.jobs = {}
        self.releases = []
        self.refs = []
        for index, (filename, names) in enumerate([
            ("project-checks.yml", ["scope", "Project checks", "api / verify", "container / image", "ios / test", "android / build", "android / device-tests"]),
            ("repository-checks.yml", ["Repository hygiene"]),
        ], 1):
            self.runs[index] = {"id": index, "workflow_id": index, "path": f".github/workflows/{filename}",
                                "head_sha": SOURCE, "head_branch": "main", "head_repository": {"full_name": REPO},
                                "event": "push", "status": "completed", "conclusion": "success", "run_attempt": 1,
                                "run_started_at": "2026-10-14T00:00:00Z"}
            self.jobs[index] = [{"name": name, "run_id": index, "run_attempt": 1, "head_sha": SOURCE,
                                 "status": "completed", "conclusion": "success", "started_at": "2026-10-14T00:00:01Z",
                                 "completed_at": "2026-10-14T00:00:02Z"} for name in names]

    def api(self, endpoint):
        path = endpoint.split("?")[0]
        if path == "":
            return {"default_branch": "main"}
        if path.startswith("compare/"):
            return {"status": "ahead", "merge_base_commit": {"sha": SOURCE}}
        if path == "releases":
            return deepcopy(self.releases)
        if path.startswith("git/matching-refs"):
            return self.refs
        if path.startswith("actions/workflows/"):
            key = path.split("/")[2]
            index = 1 if key in ("project-checks.yml", "1") else 2
            if path.endswith("/runs"):
                return {"total_count": 1, "workflow_runs": [deepcopy(self.runs[index])]}
            return {"id": index, "path": self.runs[index]["path"], "state": "active"}
        index = int(path.split("/")[2])
        if path.endswith("/jobs"):
            return {"total_count": len(self.jobs[index]), "jobs": deepcopy(self.jobs[index])}
        return deepcopy(self.runs[index])

    def test_full_main_ci_and_unused_version_accepted(self):
        evidence, releases = preflight(VERSION, SOURCE, self.api)
        self.assertEqual([1, 2], [item["run_id"] for item in evidence])
        self.assertEqual([], releases)

    def test_invalid_inputs_and_existing_draft_or_tag_rejected(self):
        for version, source in [("v1.0.0", SOURCE), ("--draft", SOURCE), (VERSION, "main"), (VERSION, "a" * 7)]:
            with self.subTest(version=version, source=source), self.assertRaises(ValueError):
                inputs(version, source)
        self.releases = [{"tag_name": VERSION, "draft": True}]
        with self.assertRaises(ValueError):
            preflight(VERSION, SOURCE, self.api)
        self.releases = []
        self.refs = [{"ref": f"refs/tags/{VERSION}"}]
        with self.assertRaises(ValueError):
            preflight(VERSION, SOURCE, self.api)

    def test_failed_skipped_cancelled_missing_and_copied_jobs_rejected(self):
        original = deepcopy(self.jobs)
        for key, value in [("conclusion", "failure"), ("conclusion", "cancelled"), ("conclusion", "skipped"),
                           ("started_at", "2026-10-13T00:00:00Z"), ("head_sha", "b" * 40)]:
            self.jobs = deepcopy(original)
            self.jobs[1][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                check_ci(SOURCE, self.api)
        self.jobs = deepcopy(original)
        self.jobs[1].pop()
        with self.assertRaises(ValueError):
            check_ci(SOURCE, self.api)

    def test_wrong_run_identity_untrusted_event_and_changed_attempt_rejected(self):
        original = deepcopy(self.runs)
        for key, value in [("head_sha", "b" * 40), ("head_branch", "feature"), ("workflow_id", 99),
                           ("head_repository", {"full_name": "attacker/fork"}), ("event", "pull_request"),
                           ("conclusion", "failure"), ("run_attempt", 2)]:
            self.runs = deepcopy(original)
            self.runs[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_ci(SOURCE, self.api)

    def artifacts(self, directory):
        (directory / ASSETS[0]).write_bytes(b"container fixture")
        (directory / ASSETS[1]).write_text(json.dumps({"version": VERSION, "source_sha": SOURCE, "artifact": "api-container"}))
        (directory / ASSETS[2]).write_text("".join(f"{digest(directory / name)}  {name}\n" for name in ASSETS[:2]))

    def test_download_verification_detects_corruption_metadata_and_extra_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.artifacts(directory)
            self.assertEqual(SOURCE, verify(directory, VERSION, SOURCE)["source_sha"])
            with self.assertRaises(ValueError):
                verify(directory, VERSION, "b" * 40)
            (directory / ASSETS[0]).write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                verify(directory, VERSION, SOURCE)
            self.artifacts(directory)
            (directory / "unexpected").touch()
            with self.assertRaises(ValueError):
                verify(directory, VERSION, SOURCE)

    def test_collision_blocks_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.artifacts(directory)
            self.releases = [{"tag_name": VERSION, "draft": True}]
            writes = []
            with self.assertRaises(ValueError):
                publish(directory, VERSION, SOURCE, self.api, lambda *args: writes.append(args))
            self.assertEqual([], writes)


if __name__ == "__main__":
    unittest.main()

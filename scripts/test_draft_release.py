from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from draft_release import ASSETS, REPO, check_ci, digest, get, inputs, preflight, publish, verify

SOURCE = "a" * 40
VERSION = "v0.1.0-alpha.20261014"


class DraftReleaseTest(unittest.TestCase):
    def setUp(self):
        self.runs = {}
        self.jobs = {}
        self.releases = []
        self.refs = []
        self.assets = []
        self.writes = []
        self.default_branch = "main"
        self.comparison = {"status": "ahead", "merge_base_commit": {"sha": SOURCE}}
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
            return {"default_branch": self.default_branch}
        if path.startswith("compare/"):
            return deepcopy(self.comparison)
        if path == "releases":
            return deepcopy(self.releases)
        if path == "releases/10":
            return deepcopy(next(item for item in self.releases if item["id"] == 10))
        if path == "releases/10/assets":
            return deepcopy(self.assets)
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

    def test_run_path_with_api_ref_suffix_is_accepted(self):
        def api_ref_suffix(endpoint):
            result = self.api(endpoint)
            if endpoint.startswith("actions/runs/") and "/jobs" not in endpoint:
                result["path"] += suffix
            return result

        for suffix in ("@main", "@refs/heads/main", f"@{SOURCE}"):
            with self.subTest(suffix=suffix):
                self.assertEqual(2, len(check_ci(SOURCE, api_ref_suffix)))
        suffix = "@refs/heads/feature"
        with self.assertRaises(ValueError):
            check_ci(SOURCE, api_ref_suffix)

    def artifacts(self, directory):
        (directory / ASSETS[0]).write_bytes(b"container fixture")
        metadata = {"version": VERSION, "source_sha": SOURCE, "artifact": "api-container",
                    "image_id": "sha256:" + "c" * 64, "os": "linux", "architecture": "amd64", "docker_version": "28.5.1",
                    "dependency_sha256": {name: "d" * 64 for name in
                        ("services/api/Cargo.lock", "services/api/Dockerfile", "rust-toolchain.toml")},
                    "ci": [{"workflow": "project-checks.yml", "run_id": 1, "attempt": 1},
                           {"workflow": "repository-checks.yml", "run_id": 2, "attempt": 1}]}
        (directory / ASSETS[1]).write_text(json.dumps(metadata))
        (directory / ASSETS[2]).write_text("".join(f"{digest(directory / name)}  {name}\n" for name in ASSETS[:2]))

    def test_preflight_uses_repository_root_through_real_gh_boundary(self):
        def gh_output(args, text):
            self.assertTrue(text)
            self.assertEqual(("gh", "api"), args[:2])
            prefix = f"repos/{REPO}"
            if args[2] == prefix + "/":
                raise subprocess.CalledProcessError(1, args, output="HTTP 404")
            endpoint = args[2][len(prefix):].removeprefix("/")
            return json.dumps(self.api(endpoint)) + "\n"

        with patch("draft_release.subprocess.check_output", side_effect=gh_output):
            evidence, releases = preflight(VERSION, SOURCE, get)
        self.assertEqual([1, 2], [item["run_id"] for item in evidence])
        self.assertEqual([], releases)

    def test_incomplete_or_invalid_build_metadata_rejected_after_checksum_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.artifacts(directory)
            original = json.loads((directory / ASSETS[1]).read_text())
            cases = []
            for key in original:
                metadata = deepcopy(original)
                del metadata[key]
                cases.append((f"missing {key}", metadata))
            for key, value in [("image_id", "sha256:short"), ("os", "windows"), ("architecture", "invalid"), ("docker_version", ""),
                               ("dependency_sha256", {"services/api/Cargo.lock": "d" * 64}),
                               ("dependency_sha256", {name: "short" for name in original["dependency_sha256"]}),
                               ("ci", [original["ci"][0]]), ("ci", [original["ci"][0], original["ci"][0]])]:
                metadata = deepcopy(original)
                metadata[key] = value
                cases.append((f"invalid {key}", metadata))
            for key, value in [("run_id", 0), ("attempt", -1), ("run_id", True), ("attempt", "1")]:
                metadata = deepcopy(original)
                metadata["ci"][0][key] = value
                cases.append((f"invalid ci {key}", metadata))
            for label, metadata in cases:
                with self.subTest(label=label):
                    (directory / ASSETS[1]).write_text(json.dumps(metadata))
                    (directory / ASSETS[2]).write_text("".join(f"{digest(directory / name)}  {name}\n" for name in ASSETS[:2]))
                    with self.assertRaises((ValueError, KeyError)):
                        verify(directory, VERSION, SOURCE)

    def gh(self, *args):
        self.writes.append(args)
        self.assertEqual(("gh", "release", "create"), args[:3])
        self.assertEqual(REPO, args[args.index("--repo") + 1])
        self.assertIn("--draft", args)
        self.assertIn("--prerelease", args)
        self.assertNotIn("--clobber", args)
        url = f"https://github.com/{REPO}/releases/tag/untagged-fixture"
        self.releases.append({"id": 10, "tag_name": args[3], "draft": True, "prerelease": True,
                              "target_commitish": args[args.index("--target") + 1], "html_url": url})
        self.assets = [{"name": Path(name).name, "size": Path(name).stat().st_size, "state": "uploaded",
                        "digest": f"sha256:{digest(Path(name))}"} for name in args[4:args.index("--repo")]]
        return url

    def test_publish_creates_private_draft_and_preserves_existing_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.artifacts(directory)
            existing = {"id": 9, "tag_name": "v0.0.1", "draft": False, "assets": [{"id": 99}]}
            self.releases = [deepcopy(existing)]
            with redirect_stdout(io.StringIO()) as output:
                publish(directory, VERSION, SOURCE, self.api, self.gh)
            self.assertEqual({"release_id": 10, "draft": True, "source_sha": SOURCE}, json.loads(output.getvalue()))
            self.assertEqual(existing, self.releases[0])
            self.assertEqual(["create"], [args[2] for args in self.writes])
            self.assertEqual(list(ASSETS), [asset["name"] for asset in self.assets])

    def test_upload_failure_leaves_private_draft_without_cleanup_or_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.artifacts(directory)

            def failed_upload(*args):
                self.gh(*args)
                self.assets.pop()
                raise subprocess.CalledProcessError(1, args)

            with self.assertRaises(subprocess.CalledProcessError):
                publish(directory, VERSION, SOURCE, self.api, failed_upload)
            self.assertTrue(self.releases[0]["draft"])
            self.assertEqual(["create"], [args[2] for args in self.writes])

    def test_publish_rejects_upload_corruption_and_concurrent_changes(self):
        for failure in ("digest", "size", "state", "missing", "public", "target", "tag", "ci", "previous",
                        "main", "default", "identity", "duplicate"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                self.artifacts(directory)
                self.releases = [{"id": 9, "tag_name": "v0.0.1", "draft": False}]
                self.refs, self.writes = [], []
                self.runs[1]["run_attempt"] = 1
                self.default_branch = "main"
                self.comparison = {"status": "ahead", "merge_base_commit": {"sha": SOURCE}}

                def corrupted_upload(*args):
                    url = self.gh(*args)
                    if failure in ("digest", "size", "state"):
                        self.assets[0][failure] = {"digest": "sha256:" + "0" * 64, "size": 0, "state": "new"}[failure]
                    elif failure == "missing":
                        self.assets.pop()
                    elif failure == "public":
                        self.releases[-1]["draft"] = False
                    elif failure == "target":
                        self.releases[-1]["target_commitish"] = "b" * 40
                    elif failure == "tag":
                        self.refs = [{"ref": f"refs/tags/{VERSION}"}]
                    elif failure == "ci":
                        self.runs[1]["run_attempt"] = 2
                    elif failure == "previous":
                        self.releases[0]["draft"] = True
                    elif failure == "main":
                        self.comparison = {"status": "diverged", "merge_base_commit": {"sha": "b" * 40}}
                    elif failure == "default":
                        self.default_branch = "other"
                    elif failure == "identity":
                        return url + "-replaced"
                    elif failure == "duplicate":
                        self.releases.append({"id": 11, "tag_name": VERSION})
                    return url

                with self.assertRaises(ValueError):
                    publish(directory, VERSION, SOURCE, self.api, corrupted_upload)
                self.assertEqual(["create"], [args[2] for args in self.writes])

    def test_source_outside_main_and_ci_rerun_during_validation_rejected(self):
        def outside_main(endpoint):
            if endpoint.startswith("compare/"):
                return {"status": "diverged", "merge_base_commit": {"sha": "b" * 40}}
            return self.api(endpoint)

        with self.assertRaises(ValueError):
            preflight(VERSION, SOURCE, outside_main)
        reads = 0

        def rerunning_ci(endpoint):
            nonlocal reads
            if endpoint == "actions/runs/1":
                reads += 1
                if reads == 2:
                    self.runs[1]["run_attempt"] = 2
            return self.api(endpoint)

        with self.assertRaises(ValueError):
            check_ci(SOURCE, rerunning_ci)

    def test_final_release_snapshot_rejects_draft_changes(self):
        for failure in ("source", "public", "identity", "duplicate"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                self.artifacts(directory)
                self.releases, self.writes = [], []
                reads = 0

                def changed_snapshot(endpoint):
                    nonlocal reads
                    if endpoint.split("?")[0] == "releases":
                        reads += 1
                        if reads == 3:
                            if failure == "source":
                                self.releases[0]["target_commitish"] = "b" * 40
                            elif failure == "public":
                                self.releases[0]["draft"] = False
                            elif failure == "identity":
                                self.releases[0]["id"] = 11
                            else:
                                self.releases.append(deepcopy(self.releases[0]))
                    return self.api(endpoint)

                with redirect_stdout(io.StringIO()) as output, self.assertRaises(ValueError):
                    publish(directory, VERSION, SOURCE, changed_snapshot, self.gh)
                self.assertEqual("", output.getvalue())
                self.assertEqual(3, reads)
                self.assertEqual(["create"], [args[2] for args in self.writes])

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

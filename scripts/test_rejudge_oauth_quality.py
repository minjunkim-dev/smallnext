"""Synthetic frozen folders at the offline rejudgment command boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import oauth_quality as qa


COMMAND = Path(__file__).with_name("rejudge_oauth_quality.py")


class RejudgmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.frozen = self.root / "frozen"
        self.output = self.root / "rejudged"
        qa.freeze(self.frozen, "quality", case_ids=["known-blocker-action-valid"], sequential=True)
        self.manifest_hash = qa.digest((self.frozen / "manifest.json").read_bytes())
        manifest = qa.load(self.frozen)
        self.row = dict(manifest["schedule"][0], index=0, matched=True, calls=[{
            "role": "check", "output": {"verdict": "accept", "criteria": [1, 2, 3, 4, 5],
                                         "evidence": "synthetic", "reason": "synthetic"},
            "cli_pid": 12345, "process_reaped": True, "process_group_alive": False,
            "provider_messages": 1, "provider_retries": 0, "additional_provider_requests": 0,
            "max_tokens": 0, "actual_models": [qa.MODEL]}], manifest_sha256=self.manifest_hash)
        (self.frozen / "results").mkdir()
        self.write("results/000.json", self.row)
        self.write("run-started.json", {"manifest_sha256": self.manifest_hash})
        self.write("summary.json", {"passed": True, "cancelled": False})

    def write(self, name, value):
        (self.frozen / name).write_bytes(qa.encoded(value))

    def snapshot(self):
        return {str(p.relative_to(self.frozen)): p.read_bytes()
                for p in self.frozen.rglob("*") if p.is_file()}

    def command(self, *, output=None, frozen=None, env=None, script=COMMAND):
        return subprocess.run([sys.executable, str(script), "--frozen", str(frozen or self.frozen),
                               "--output", str(output or self.output)],
                              capture_output=True, text=True, env=env, timeout=10)

    def report(self):
        return json.loads((self.output / "report.json").read_bytes())

    def change_manifest(self, change):
        manifest = json.loads((self.frozen / "manifest.json").read_bytes())
        change(manifest)
        self.write("manifest.json", manifest)
        self.manifest_hash = qa.digest((self.frozen / "manifest.json").read_bytes())
        self.write("integrity.json", {"manifest_sha256": self.manifest_hash})
        self.write("run-started.json", {"manifest_sha256": self.manifest_hash})
        self.row["manifest_sha256"] = self.manifest_hash
        self.write("results/000.json", self.row)

    def test_complete_flat_call_passes_without_changing_input(self):
        before = self.snapshot()
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.report()
        self.assertEqual(report["original_verdict"], "passed")
        self.assertEqual(report["new_verdict"], "passed")
        self.assertEqual(report["cases"][0]["new_verdict"], "passed")
        self.assertEqual(before, self.snapshot())

    def test_explicit_failures_override_old_pass_and_missing_evidence(self):
        for fields, reason in [({"error": ""}, "explicit_error"),
                               ({"error": None}, "explicit_error"),
                               ({"error": False}, "explicit_error"),
                               ({"error": "cancelled"}, "cancelled"),
                               ({"error": "timed_out"}, "timed_out"),
                               ({"process_reaped": False}, "process_cleanup"),
                               ({"process_group_alive": True}, "process_cleanup"),
                               ({"subcalls": [{"error": "cancelled"}]}, "cancelled")]:
            with self.subTest(fields=fields):
                self.row["calls"][0].update(fields)
                self.write("results/000.json", self.row)
                self.output = self.root / f"report-{reason}-{len(list(self.root.iterdir()))}"
                result = self.command()
                self.assertEqual(result.returncode, 1, result.stderr)
                report = self.report()
                self.assertEqual(report["original_verdict"], "passed")
                self.assertEqual(report["new_verdict"], "failed")
                self.assertIn(reason, report["cases"][0]["reasons"])
                for key in fields:
                    self.row["calls"][0].pop(key)
                self.row["calls"][0].update(process_reaped=True, process_group_alive=False)

    def test_missing_completion_evidence_is_indeterminate(self):
        for key in ("cli_pid", "process_reaped", "process_group_alive", "output", "provider_messages",
                    "provider_retries", "additional_provider_requests", "max_tokens", "actual_models"):
            with self.subTest(key=key):
                value = self.row["calls"][0].pop(key)
                self.write("results/000.json", self.row)
                self.output = self.root / f"missing-{key}"
                result = self.command()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.report()["new_verdict"], "indeterminate")
                self.assertIn("completion_unverifiable", self.report()["cases"][0]["reasons"])
                self.row["calls"][0][key] = value

    def test_missing_or_malformed_calls_never_pass(self):
        for calls in ([], None, [None], [{"role": "generate"}], [{"subcalls": None}],
                      [dict(self.row["calls"][0], subcalls=[])],
                      [dict(self.row["calls"][0], process_reaped=1)],
                      [dict(self.row["calls"][0], provider_messages=True)],
                      [dict(self.row["calls"][0], output={"verdict": "accept"})],
                      [dict(self.row["calls"][0], calls=None)]):
            with self.subTest(calls=calls):
                self.write("results/000.json", dict(self.row, calls=calls))
                self.output = self.root / f"malformed-{len(list(self.root.iterdir()))}"
                result = self.command()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.report()["new_verdict"], "indeterminate")

    def test_reference_mismatch_is_a_fixed_failure_reason(self):
        self.row["matched"] = False
        self.write("results/000.json", self.row)
        result = self.command()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.report()["new_verdict"], "failed")
        self.assertIn("reference_mismatch", self.report()["cases"][0]["reasons"])

    def test_corrupt_or_missing_result_remains_indeterminate(self):
        path = self.frozen / "results/000.json"
        for raw in (None, b'{"matched":', b'[]', b'{"matched":true,"matched":false}', b'\xff'):
            with self.subTest(raw=raw):
                path.unlink(missing_ok=True)
                if raw is not None:
                    path.write_bytes(raw)
                self.output = self.root / f"corrupt-{len(list(self.root.iterdir()))}"
                result = self.command()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.report()["new_verdict"], "indeterminate")

    def test_missing_or_corrupt_summary_and_claim_never_pass(self):
        for name, value in (("summary.json", None), ("summary.json", b'{'),
                            ("summary.json", qa.encoded({"passed": True})),
                            ("summary.json", qa.encoded({"passed": True, "cancelled": 0})),
                            ("run-started.json", None), ("run-started.json", b'null')):
            with self.subTest(name=name, value=value):
                path = self.frozen / name
                before = path.read_bytes()
                path.unlink()
                if value is not None:
                    path.write_bytes(value)
                self.output = self.root / f"metadata-{len(list(self.root.iterdir()))}"
                result = self.command()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.report()["new_verdict"], "indeterminate")
                path.write_bytes(before)

    def test_cancellation_markers_and_summary_cancellation_fail(self):
        for marker in (True, False):
            with self.subTest(marker=marker):
                if marker:
                    self.write("run-cancelled.json", {"error": "cancelled"})
                else:
                    (self.frozen / "run-cancelled.json").unlink()
                    self.write("summary.json", {"passed": True, "cancelled": True})
                self.output = self.root / f"cancelled-{marker}"
                result = self.command()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.report()["new_verdict"], "failed")
                self.assertIn("cancelled", self.report()["reasons"])

    def test_unknown_frozen_source_is_not_executed_and_original_recovery_stays_strict(self):
        sentinel = "PRIVATE_SENTINEL"
        marker = self.root / "executed"

        def change(manifest):
            source = manifest["sources"]["scripts/oauth_quality.py"]
            source["utf8"] += f"\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n# {sentinel}\n"
            source["sha256"] = qa.digest(source["utf8"].encode())

        self.change_manifest(change)
        fake = self.root / "claude"
        fake.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n")
        fake.chmod(0o700)
        env = dict(os.environ, PATH=str(self.root))
        before = self.snapshot()
        result = self.command(env=env)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.report()["new_verdict"], "indeterminate")
        self.assertEqual(self.report()["protocol"], "unknown")
        self.assertFalse(marker.exists())
        self.assertEqual(before, self.snapshot())
        self.assertNotIn(sentinel, result.stdout + result.stderr + (self.output / "report.json").read_text())
        for command in ("verify", "summarize"):
            original = subprocess.run([sys.executable, qa.__file__, command, str(self.frozen)],
                                      capture_output=True, text=True, env=env, timeout=10)
            self.assertNotEqual(original.returncode, 0)
            self.assertIn("runner differs from frozen version", original.stderr)
        self.assertFalse(marker.exists())

    def test_identical_request_reuses_complete_result_without_replacing_bytes(self):
        self.assertEqual(self.command().returncode, 0)
        report = self.output / "report.json"
        before = report.read_bytes(), report.stat().st_ino, report.stat().st_mtime_ns
        self.assertEqual(self.command().returncode, 0)
        self.assertEqual(before, (report.read_bytes(), report.stat().st_ino, report.stat().st_mtime_ns))
        data = self.report()
        self.assertEqual(data["input_files"]["results/000.json"],
                         qa.digest((self.frozen / "results/000.json").read_bytes()))
        self.assertEqual(data["fingerprint_scope"], "observed_bytes_only; not_historical_authenticity")
        self.assertNotEqual(data["policy_sha256"], data["original_runner_sha256"])

    def test_changed_input_or_policy_and_corrupt_report_refuse_replacement(self):
        self.assertEqual(self.command().returncode, 0)
        report = self.output / "report.json"
        original = report.read_bytes()
        self.write("summary.json", {"passed": False, "cancelled": False})
        self.assertEqual(self.command().returncode, 2)
        self.assertEqual(original, report.read_bytes())
        self.write("summary.json", {"passed": True, "cancelled": False})
        trusted = self.root / "trusted"
        trusted.mkdir()
        copied = trusted / COMMAND.name
        copied.write_bytes(COMMAND.read_bytes() + b"\n# trusted policy changed\n")
        (trusted / "oauth_quality.py").write_bytes(Path(qa.__file__).read_bytes())
        (trusted / "launch_evaluation.py").write_bytes(COMMAND.with_name("launch_evaluation.py").read_bytes())
        self.assertEqual(self.command(script=copied).returncode, 2)
        self.assertEqual(original, report.read_bytes())
        report.write_bytes(b"corrupt")
        self.assertEqual(self.command().returncode, 2)
        self.assertEqual(report.read_bytes(), b"corrupt")

    def test_output_path_cannot_overlap_input_even_through_symlink(self):
        link = self.root / "alias"
        link.symlink_to(self.frozen, target_is_directory=True)
        before = self.snapshot()
        for path in (self.frozen, self.frozen / "nested", self.root, link / "nested"):
            with self.subTest(path=path):
                self.assertEqual(self.command(output=path).returncode, 2)
        self.assertEqual(before, self.snapshot())

    def test_input_file_and_results_directory_symlinks_are_rejected(self):
        original = self.frozen / "results/000.json"
        outside = self.root / "private.json"
        outside.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(outside)
        self.assertEqual(self.command().returncode, 2)
        original.unlink()
        (self.frozen / "results").rmdir()
        external = self.root / "external"
        external.mkdir()
        (external / "000.json").write_bytes(outside.read_bytes())
        (self.frozen / "results").symlink_to(external, target_is_directory=True)
        self.assertEqual(self.command().returncode, 2)

    def test_explicit_error_text_and_input_labels_never_leave_report_or_cli(self):
        sentinel = "PRIVATE_SENTINEL"
        self.row["error"] = sentinel
        self.row["calls"][0]["output"]["reason"] = sentinel
        self.row["case"] = sentinel
        self.row["variant"] = sentinel
        self.write("results/000.json", self.row)
        result = self.command()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.report()["new_verdict"], "failed")
        self.assertNotIn(sentinel, result.stdout + result.stderr + (self.output / "report.json").read_text())

    def test_unsupported_input_and_broken_manifest_integrity_are_rejected(self):
        for change in (lambda m: m.update(version=2), lambda m: m.update(version=True),
                       lambda m: m.update(suite="launch"), lambda m: m.update(cases=[]),
                       lambda m: m.update(schedule=[{"case": "unknown", "variant": "baseline", "repeat": 0}])):
            with self.subTest(change=change):
                before = self.snapshot()
                self.change_manifest(change)
                self.assertEqual(self.command().returncode, 2)
                for name, raw in before.items():
                    (self.frozen / name).write_bytes(raw)
        path = self.frozen / "manifest.json"
        path.write_bytes(path.read_bytes() + b" ")
        self.assertEqual(self.command().returncode, 2)
        summary_only = self.root / "summary-only.json"
        summary_only.write_bytes(qa.encoded({"passed": True}))
        self.assertEqual(self.command(frozen=summary_only).returncode, 2)

    def test_unexpected_results_and_false_or_untyped_summary_do_not_become_passes(self):
        self.write("results/PRIVATE_SENTINEL.json", self.row)
        result = self.command()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.report()["new_verdict"], "indeterminate")
        self.assertIn("unexpected_results", self.report()["reasons"])
        self.assertNotIn("PRIVATE_SENTINEL", (self.output / "report.json").read_text())
        (self.frozen / "results/PRIVATE_SENTINEL.json").unlink()
        for passed in (False, 1, None):
            with self.subTest(passed=passed):
                self.write("summary.json", {"passed": passed, "cancelled": False})
                self.output = self.root / f"summary-{passed}"
                self.assertEqual(self.command().returncode, 1)
                self.assertEqual(self.report()["new_verdict"], "indeterminate")

    def test_generate_then_check_pipeline_retains_original_reference_judgment(self):
        complete = self.root / "complete"
        qa.freeze(complete, "quality", sequential=True)
        manifest = qa.load(complete)
        case = next(c for c in manifest["cases"] if c["id"] == "useful-minimum-known")
        candidate = next(c["candidate"] for c in manifest["cases"] if c["id"] == "known-blocker-action-valid")

        def change(manifest):
            manifest["cases"] = [case]
            manifest["schedule"] = [{"case": case["id"], "variant": "baseline", "repeat": 0}]

        self.row["case"] = case["id"]
        generated = dict(self.row["calls"][0], role="generate", output=candidate)
        self.row["calls"].insert(0, generated)
        self.change_manifest(change)
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.report()["new_verdict"], "passed")

    def test_source_integrity_duplicate_manifest_and_nonfinite_numbers_are_rejected(self):
        original = (self.frozen / "manifest.json").read_bytes()
        manifest = json.loads(original)
        manifest["sources"]["scripts/oauth_quality.py"]["utf8"] += "\n# changed\n"
        self.write("manifest.json", manifest)
        self.write("integrity.json", {"manifest_sha256": qa.digest((self.frozen / "manifest.json").read_bytes())})
        self.assertEqual(self.command().returncode, 2)
        for bad in (original.replace(b'"version": 1', b'"version": 1, "version": 1', 1),
                    original.replace(b'"version": 1', b'"version": NaN', 1)):
            (self.frozen / "manifest.json").write_bytes(bad)
            self.write("integrity.json", {"manifest_sha256": qa.digest(bad)})
            self.assertEqual(self.command().returncode, 2)


if __name__ == "__main__":
    unittest.main()

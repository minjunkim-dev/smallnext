"""Offline tests at the manual evaluator's freeze/run boundary."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import contextlib
import io
import unittest

import oauth_quality as qa


class FrozenEvaluationTests(unittest.TestCase):
    def test_freeze_keeps_legacy_reference_and_excludes_answers_from_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "quality")
            manifest = qa.load(frozen)
            known = next(c for c in manifest["cases"] if c["id"] == "useful-minimum-known")
            self.assertEqual(known["legacy_statuses"], ["minimum"])
            self.assertEqual(known["expected_statuses"], ["action", "minimum"])
            self.assertEqual(len(manifest["cases"]), 47)
            self.assertEqual(sum("input" in c for c in manifest["cases"]), 14)
            self.assertEqual(qa.payload(known, "generate"), known["input"])
            candidate = {"status": "minimum"}
            self.assertEqual(qa.payload(known, "check", candidate), {
                "original_request": known["input"], "candidate": candidate,
            })
            original = qa.REPO / "docs/research/fixtures/status-contract-checks.json"
            self.assertEqual(manifest["sources"][original.relative_to(qa.REPO).as_posix()]["sha256"],
                             hashlib.sha256(original.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                qa.freeze(frozen, "quality")

    def test_paired_order_and_manifest_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            role = Path(directory) / "role.md"
            role.write_text("Check the candidate once.", encoding="utf-8")
            qa.freeze(frozen, "latency", role, 2)
            manifest = qa.load(frozen)
            self.assertEqual([row["variant"] for row in manifest["schedule"]],
                             ["baseline", "comparison", "comparison", "baseline",
                              "comparison", "baseline", "baseline", "comparison"])
            self.assertEqual(len(manifest["cases"]), 2)
            original = (frozen / "manifest.json").read_bytes()
            (frozen / "manifest.json").write_bytes(original + b" ")
            with self.assertRaisesRegex(ValueError, "manifest changed"):
                qa.load(frozen)

    def test_targeted_freeze_pins_only_known_cases_without_payload_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qa.freeze(root / "probe", "quality", case_ids=["replacement-empty-invalid", "generate-next"])
            manifest = qa.load(root / "probe")
            self.assertEqual({c["id"] for c in manifest["cases"]}, {"replacement-empty-invalid", "generate-next"})
            self.assertEqual(len(manifest["schedule"]), 2)
            self.assertNotIn("case_ids", qa.payload(manifest["cases"][0], "check"))
            with self.assertRaisesRegex(ValueError, "unknown case"):
                qa.freeze(root / "invalid", "quality", case_ids=["unknown"])
            self.assertFalse((root / "invalid").exists())

    def test_stream_failure_never_saves_reasoning_or_credentials(self):
        tracker = qa.Tracker()
        tracker.consume({"type": "stream_event", "event": {"type": "message_start"}}, 1)
        tracker.consume({"type": "stream_event", "event": {
            "type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "PRIVATE"}
        }}, 2)
        with self.assertRaisesRegex(ValueError, "additional_provider_request"):
            tracker.consume({"type": "stream_event", "event": {"type": "message_start"}}, 3)
        record = json.dumps(tracker.metadata())
        self.assertNotIn("PRIVATE", record)
        self.assertEqual(tracker.metadata()["provider_messages"], 2)
        self.assertEqual(tracker.metadata()["additional_provider_requests"], 1)

    def test_safe_trace_identifies_schema_repair_before_second_message(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
                  "required": ["ok"], "additionalProperties": False}
        tracker = qa.Tracker(schema)
        tracker.consume({"type": "stream_event", "event": {"type": "message_start",
                         "message": {"id": "PRIVATE-ID"}}}, 1)
        tracker.consume({"type": "stream_event", "event": {"type": "content_block_start",
                         "index": 0, "content_block": {"type": "thinking", "thinking": "SECRET"}}}, 2)
        tracker.consume({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}}, 4)
        tracker.consume({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "StructuredOutput", "input": {"ok": "SECRET"}}]}}, 5)
        tracker.consume({"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "PRIVATE-error"}]}}, 6)
        with self.assertRaisesRegex(ValueError, "additional_provider_request"):
            tracker.consume({"type": "stream_event", "event": {"type": "message_start",
                             "message": {"id": "PRIVATE-ID"}}}, 7)
        metadata = tracker.metadata()
        self.assertIn({"event": "structured_output", "schema_valid": False, "seconds": 5}, metadata["trace"])
        self.assertIn({"event": "tool_result", "is_error": True, "seconds": 6}, metadata["trace"])
        self.assertTrue(metadata["trace"][-1]["duplicate_id"])
        self.assertEqual(metadata["block_seconds"]["thinking"], 2)
        self.assertNotIn("PRIVATE", json.dumps(metadata))
        self.assertNotIn("SECRET", json.dumps(metadata))

    def test_runner_verifies_effective_model_and_reaps_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "claude"
            fake.write_text("#!/usr/bin/env python3\nimport json\n"
                            "print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))\n"
                            "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
                            "'modelUsage':{'wrong':{}},'structured_output':{'ok':True}}))\n")
            fake.chmod(0o700)
            schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
                      "required": ["ok"], "additionalProperties": False}
            result = qa.call(str(fake), "prompt", schema, {}, qa.monotonic() + 2, threading.Event())
            self.assertEqual(result["error"], "wrong_model")
            self.assertTrue(result["process_reaped"])
            self.assertNotIn("output", result)
            fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
            result = qa.call(str(fake), "prompt", schema, {}, qa.monotonic() + .1, threading.Event())
            self.assertEqual(result["error"], "timed_out")
            self.assertTrue(result["process_reaped"])
            self.assertFalse(result["process_group_alive"])

    def test_success_validates_all_five_criteria_and_run_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen"
            qa.freeze(frozen, "latency")
            fake = root / "claude"
            fake.write_text("#!/usr/bin/env python3\nimport json,sys\n"
                "if sys.argv[1:]==['auth','status']:\n"
                " print(json.dumps({'loggedIn':True,'authMethod':'claude.ai','apiProvider':'firstParty'}))\n"
                " sys.exit()\n"
                "data=json.load(sys.stdin)\n"
                "assert set(data)=={'original_request','candidate'}\n"
                "print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))\n"
                "print(json.dumps({'type':'stream_event','event':{'type':'content_block_delta',"
                "'delta':{'type':'thinking_delta','thinking':'DO-NOT-SAVE'}}}))\n"
                "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
                "'modelUsage':{'claude-haiku-5-5':{}},'duration_api_ms':2000,"
                "'errors':['DO-NOT-SAVE'],'structured_output':"
                "{'verdict':'accept','criteria':[1,2,3,4,5],'evidence':'one quote','reason':'fits'}}))\n")
            fake.chmod(0o700)
            command = [sys.executable, str(qa.REPO / "scripts/oauth_quality.py"),
                       "run", str(frozen), "--claude", str(fake)]
            result = subprocess.run(command, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((frozen / "summary.json").read_bytes())
            self.assertEqual(summary["matched"], 4)
            self.assertEqual(summary["provider_messages"], 4)
            self.assertEqual(summary["timings"]["baseline"]["median"], 2)
            self.assertEqual(summary["legacy_baseline"]["status_matched"], 13)
            before = (frozen / "results/000.json").read_bytes()
            again = subprocess.run(command, capture_output=True, timeout=10)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual((frozen / "results/000.json").read_bytes(), before)
            self.assertNotIn("DO-NOT-SAVE", b"".join(p.read_bytes() for p in frozen.rglob("*.json")).decode())
            self.assertFalse(qa.check_valid({"verdict":"accept", "criteria":[1,2,3,4],
                                             "evidence":"quote", "reason":"fits"}))

    def test_cancel_max_tokens_and_retry_are_separate_failures(self):
        cancel = threading.Event()
        cancel.set()
        result = qa.call("must-not-start", "", {}, {}, qa.monotonic() + 2, cancel)
        self.assertEqual(result["error"], "cancelled")
        self.assertNotIn("cli_pid", result)
        for event, error in [
            ({"type":"stream_event", "event":{"type":"message_delta", "delta":{"stop_reason":"max_tokens"}}}, "max_tokens"),
            ({"type":"system", "subtype":"api_retry", "error":{"message":"SECRET"}}, "provider_retry"),
        ]:
            tracker = qa.Tracker()
            with self.assertRaisesRegex(ValueError, error):
                tracker.consume(event, 1)
            self.assertNotIn("SECRET", json.dumps(tracker.metadata()))

    def test_active_cancellation_reaps_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "claude"
            fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
            fake.chmod(0o700)
            cancel = threading.Event()
            timer = threading.Timer(.1, cancel.set)
            timer.start()
            result = qa.call(str(fake), "", {}, {}, qa.monotonic() + 5, cancel)
            timer.join()
            self.assertEqual(result["error"], "cancelled")
            self.assertTrue(result["process_reaped"])
            self.assertFalse(result["process_group_alive"])

    def test_schema_and_preservation_reject_wrong_types_and_empty_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "quality")
            manifest = qa.load(frozen)
            output = {"verdict":"accept", "criteria":[True,2,3,4,5], "evidence":"x", "reason":"x"}
            with self.assertRaisesRegex(ValueError, "invalid_output"):
                qa.validate(output, manifest["schemas"]["check"])
            output["criteria"] = [1,2,3,4,5]
            output["evidence"] = " "
            self.assertFalse(qa.check_valid(output))
            for c in manifest["cases"]:
                if "input" in c:
                    schema = qa.schema_for(manifest, c["input"])
                    if c["input"]["request_kind"] == "goal_preparation":
                        # This case must permit only a draft or a necessary question.
                        self.assertEqual(schema["properties"]["status"]["enum"], ["goal_summary", "need_info"])
                    else:
                        self.assertNotIn("goal_summary", schema["properties"]["status"]["enum"])

    def test_malformed_stream_and_usage_fail_without_losing_failure_record(self):
        tracker = qa.Tracker()
        with self.assertRaisesRegex(ValueError, "invalid_stream"):
            tracker.consume(["unexpected event"], 1)
        tracker.consume({"type":"result", "usage":None, "modelUsage":None}, 2)
        self.assertEqual(tracker.metadata()["actual_models"], [])

    def test_summary_separates_provider_failure_from_reference_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "latency")
            manifest = qa.load(frozen)
            call = qa.Tracker().metadata() | {"role":"check", "error":"cancelled", "process_reaped":False}
            records = [dict(manifest["schedule"][0], index=0, calls=[call], matched=False, legacy_matched=False)]
            qa.summarize(frozen, manifest, records)
            summary = json.loads((frozen / "summary.json").read_bytes())
            self.assertEqual(summary["failed_cases"], 1)
            self.assertEqual(summary["reference_mismatches"], 0)
            self.assertEqual(summary["cancelled_role_calls"], 1)
            self.assertEqual(summary["failed_role_calls"], 0)

    def test_frozen_artifact_is_portable_and_runner_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen"
            qa.freeze(frozen, "latency")
            result = subprocess.run([sys.executable, str(qa.REPO / "scripts/oauth_quality.py"),
                                     "verify", str(frozen)], cwd=root, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = qa.load(frozen)
            source = manifest["sources"]["scripts/oauth_quality.py"]
            source["utf8"] += "\n# changed runner\n"
            source["sha256"] = hashlib.sha256(source["utf8"].encode()).hexdigest()
            (frozen / "manifest.json").write_bytes(qa.encoded(manifest))
            (frozen / "integrity.json").write_bytes(qa.encoded({
                "manifest_sha256": hashlib.sha256((frozen / "manifest.json").read_bytes()).hexdigest()}))
            with self.assertRaisesRegex(ValueError, "runner differs"):
                qa.load(frozen)

    def test_generation_and_checker_share_one_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / "frozen"
            qa.freeze(frozen, "quality")
            manifest = qa.load(frozen)
            manifest["pipeline_seconds"] = 1
            (frozen / "results").mkdir()
            fake = root / "claude"
            fake.write_text("#!/usr/bin/env python3\nimport json,sys,time\ndata=json.load(sys.stdin)\n"
                "time.sleep(.6)\n"
                "out={'verdict':'accept','criteria':[1,2,3,4,5],'evidence':'quote','reason':'fits'}\n"
                "if 'candidate' not in data:\n"
                " out={'status':'action','action':'두 손으로 책 한 권을 아래 칸에 놓는다.',"
                "'completion_condition':'책 한 권이 아래 칸에 있다.','estimated_minutes':1,'reason':'막힘 해결',"
                "'remaining_work':data['remaining_work'],'preserved_completed_ids':data['completed_ids'],"
                "'goal_completed':False,'current_action_completed':False}\n"
                "print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))\n"
                "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
                "'modelUsage':{'claude-haiku-5-5':{}},'structured_output':out}))\n")
            fake.chmod(0o700)
            record = qa.evaluate(frozen, manifest, 0,
                {"case":"useful-minimum-known", "variant":"baseline", "repeat":0}, str(fake), threading.Event())
            self.assertEqual(len(record["calls"]), 2)
            self.assertIn("output", record["calls"][0])
            self.assertEqual(record["calls"][1]["error"], "timed_out")
            if "cli_pid" in record["calls"][1]:
                self.assertTrue(record["calls"][1]["process_reaped"])
            self.assertFalse(record["matched"])

    def test_partial_summary_recovery_never_retries_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "latency")
            (frozen / "results").mkdir()
            qa.save(frozen / "run-started.json", {
                "manifest_sha256": hashlib.sha256((frozen / "manifest.json").read_bytes()).hexdigest()})
            with contextlib.redirect_stdout(io.StringIO()):
                qa.recover_summary(frozen)
            summary = json.loads((frozen / "summary.json").read_bytes())
            self.assertEqual(summary["recorded"], 0)
            self.assertFalse(summary["passed"])
            before = (frozen / "summary.json").read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                qa.recover_summary(frozen)
            self.assertEqual((frozen / "summary.json").read_bytes(), before)

    def test_unexpected_evaluator_failure_keeps_a_failed_case_record(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "quality")
            manifest = qa.load(frozen)
            (frozen / "results").mkdir()
            candidate = next(c["candidate"] for c in manifest["cases"] if c["id"] == "known-blocker-action-valid")
            row = {"case":"useful-minimum-known", "variant":"baseline", "repeat":0}
            with patch.object(qa, "call", side_effect=[{"output":candidate}, RuntimeError("PRIVATE")]):
                record = qa.evaluate(frozen, manifest, 0, row, "unused", threading.Event())
            self.assertEqual(record["error"], "runner_failed")
            self.assertFalse(record["matched"])
            self.assertEqual(len(record["calls"]), 1)
            self.assertNotIn("PRIVATE", (frozen / "results/000.json").read_text())

    def test_recovery_checks_birth_identity_and_manifest_identity(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "latency")
            (frozen / "results").mkdir()
            claim = {"manifest_sha256": hashlib.sha256((frozen / "manifest.json").read_bytes()).hexdigest(),
                     "controller_pid": 123, "controller_birth": "original"}
            qa.save(frozen / "run-started.json", claim)
            with patch.object(qa, "process_birth", return_value="original"):
                with self.assertRaisesRegex(ValueError, "still alive"):
                    qa.recover_summary(frozen)
            qa.save(frozen / "results/000.json", {"manifest_sha256":"different"})
            with patch.object(qa, "process_birth", return_value="reused PID"):
                with self.assertRaisesRegex(ValueError, "different manifest"):
                    qa.recover_summary(frozen)

    def test_duplicate_results_cannot_turn_partial_execution_into_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "latency")
            manifest = qa.load(frozen)
            row = dict(manifest["schedule"][0], index=0, calls=[], matched=True, legacy_matched=False)
            with self.assertRaisesRegex(ValueError, "duplicate or unrelated"):
                qa.summarize(frozen, manifest, [row] * 4)
            self.assertFalse((frozen / "summary.json").exists())

    def test_truncated_result_preserves_valid_results_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "latency")
            manifest = qa.load(frozen)
            manifest_hash = hashlib.sha256((frozen / "manifest.json").read_bytes()).hexdigest()
            (frozen / "results").mkdir()
            qa.save(frozen / "run-started.json", {"manifest_sha256":manifest_hash})
            good = dict(manifest["schedule"][0], index=0, calls=[], matched=True, legacy_matched=False,
                        manifest_sha256=manifest_hash)
            qa.save(frozen / "results/000.json", good)
            (frozen / "results/001.json").write_bytes(b'{"calls":')
            before = (frozen / "results/000.json").read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                qa.recover_summary(frozen)
            summary = json.loads((frozen / "summary.json").read_bytes())
            self.assertEqual(summary["recorded"], 1)
            self.assertEqual(summary["unreadable_records"], ["001.json"])
            self.assertEqual(summary["missing_cases"], 3)
            self.assertFalse(summary["passed"])
            self.assertEqual((frozen / "results/000.json").read_bytes(), before)
            self.assertEqual((frozen / "results/001.json").read_bytes(), b'{"calls":')

    def test_truncated_summary_is_recovered_without_overwriting_original(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "latency")
            manifest = qa.load(frozen)
            manifest_hash = hashlib.sha256((frozen / "manifest.json").read_bytes()).hexdigest()
            (frozen / "results").mkdir()
            qa.save(frozen / "run-started.json", {"manifest_sha256":manifest_hash})
            qa.save(frozen / "results/000.json", dict(manifest["schedule"][0], index=0, calls=[],
                matched=True, legacy_matched=False, manifest_sha256=manifest_hash))
            (frozen / "summary.json").write_bytes(b'{"passed":')
            with contextlib.redirect_stdout(io.StringIO()):
                qa.recover_summary(frozen)
            recovered = json.loads((frozen / "summary-recovered.json").read_bytes())
            self.assertEqual(recovered["recorded"], 1)
            self.assertFalse(recovered["passed"])
            self.assertEqual((frozen / "summary.json").read_bytes(), b'{"passed":')
            before = (frozen / "summary-recovered.json").read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                qa.recover_summary(frozen)
            self.assertEqual((frozen / "summary-recovered.json").read_bytes(), before)

    def test_interrupted_atomic_save_leaves_no_partial_target(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "record.json"
            with patch.object(qa.os, "link", side_effect=RuntimeError("interrupted")):
                with self.assertRaises(RuntimeError):
                    qa.save(target, {"value":1})
            self.assertFalse(target.exists())
            qa.save(target, {"value":1})
            with self.assertRaises(FileExistsError):
                qa.save(target, {"value":2})
            self.assertEqual(json.loads(target.read_bytes()), {"value":1})

    def test_invalid_candidate_is_not_sent_to_checker(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "quality")
            manifest = qa.load(frozen)
            (frozen / "results").mkdir()
            case = next(c for c in manifest["cases"] if c["id"] == "useful-minimum-known")
            output = next(c["candidate"] for c in manifest["cases"] if c["id"] == "known-blocker-action-valid")
            # Completed flag violates preservation even if the checker would accept.
            output["goal_completed"] = True
            with patch.object(qa, "call", return_value={"output": output}) as provider:
                record = qa.evaluate(frozen, manifest, 0, {"case":case["id"], "variant":"baseline", "repeat":0},
                                     "unused", threading.Event())
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(record["error"], "invalid_proposal")
            self.assertFalse(record["matched"])


if __name__ == "__main__":
    unittest.main()

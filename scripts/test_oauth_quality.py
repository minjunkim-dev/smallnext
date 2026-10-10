"""Offline tests at the manual evaluator's freeze/run boundary."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
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

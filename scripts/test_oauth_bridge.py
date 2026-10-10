"""Offline tests at the Rust CLI adapter boundary. No subscription calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import oauth_bridge as bridge


class OAuthBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.schema = self.root / "schema.json"
        self.schema.write_text(json.dumps({"type": "object", "properties": {"ok": {"type": "boolean"}},
                                          "required": ["ok"], "additionalProperties": False}))
        self.prompt = self.root / "system.md"
        self.prompt.write_text("original contract")
        self.fake = self.root / "claude"
        self.fake.write_text("#!/usr/bin/env python3\nimport json,sys\n"
            "assert '--json-schema' in sys.argv\n"
            "assert sys.argv[sys.argv.index('--effort')+1]=='xhigh'\n"
            "assert sys.argv[sys.argv.index('--model')+1]=='claude-haiku-5-5'\n"
            "print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))\n"
            "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
            "'modelUsage':{'claude-haiku-5-5':{}},'result':json.dumps({'ok':True}),'structured_output':{'ok':True}}))\n")
        self.fake.chmod(0o700)
        self.command = [sys.executable, str(Path(bridge.__file__)), "--claude", str(self.fake),
                        "--records", str(self.root / "records"), "--output-schema", str(self.schema),
                        "-c", "model_instructions_file=" + json.dumps(str(self.prompt))]

    def invoke(self):
        return subprocess.run(self.command, input="{}", text=True, capture_output=True, timeout=5)

    def test_default_structured_json_reaches_rust_event_parser(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(events[-1], {"type": "turn.completed"})
        self.assertEqual(json.loads(events[0]["item"]["text"]), {"ok": True})
        record = json.loads(next((self.root / "records").glob("*.json")).read_text())
        self.assertEqual(record["output_mode"], "structured")
        self.assertEqual(record["provider_messages"], 1)
        self.assertEqual(record["requested_effort"], "xhigh")
        self.assertNotIn("output", record)

    def test_invalid_json_and_additional_messages_never_complete(self):
        original = self.fake.read_text()
        for content in [original.replace("{'ok':True}", "{'ok':'PRIVATE'}"),
                        original.replace("print(json.dumps({'type':'result'", "print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))\nprint(json.dumps({'type':'result'")]:
            self.fake.write_text(content)
            result = self.invoke()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("turn.completed", result.stdout)
            self.assertNotIn("PRIVATE", result.stdout)
        self.assertNotIn("PRIVATE", "".join(p.read_text() for p in (self.root / "records").glob("*.json")))
        records = [json.loads(p.read_text()) for p in (self.root / "records").glob("*.json")]
        invalid = next(r for r in records if r.get("error") == "invalid_output")
        self.assertEqual(invalid["output_error"], {"kind": "type", "path": "$.ok"})
        self.assertNotIn("output", invalid)

    def test_domain_guard_reports_only_field_names_without_repairing_output(self):
        schema = Path(bridge.__file__).parent.parent / "services/api/src/development_ai/generate.json"
        self.schema.write_text(schema.read_text())
        candidate = {"status": "need_info", "action": " ", "completion_condition": "Answered",
                     "reason": "PRIVATE", "estimated_minutes": 1}
        self.fake.write_text("#!/usr/bin/env python3\nimport json\n"
            "print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))\n"
            "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
            "'modelUsage':{'claude-haiku-5-5':{}},'structured_output':" + repr(candidate) + "}))\n")
        data = {"available_minutes": 5, "remaining_work": ["required work"], "completed_ids": ["done"]}
        result = subprocess.run(self.command, input=json.dumps(data), text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        # Rust still owns the guard; the adapter must not repair or accept its proposal itself.
        item = json.loads(result.stdout.splitlines()[0])["item"]
        self.assertEqual(json.loads(item["text"]), dict(candidate, remaining_work=data["remaining_work"],
            preserved_completed_ids=data["completed_ids"], goal_completed=False, current_action_completed=False))
        record = json.loads(next((self.root / "records").glob("*.json")).read_text())
        self.assertEqual(record["invalid_proposal_fields"], ["action"])
        self.assertNotIn("PRIVATE", json.dumps(record))
        self.assertNotIn("output", record)

    def test_adapter_kill_reaps_claude_without_parent_handler(self):
        marker = self.root / "pids"
        marker.mkdir()
        self.schema.write_bytes((Path(bridge.__file__).parent.parent /
                                 "services/api/src/development_ai/check.json").read_bytes())
        self.fake.write_text("#!/usr/bin/env python3\nimport os,time\nfrom pathlib import Path\n"
                            + f"(Path({str(marker)!r})/str(os.getpid())).touch()\n"
                            + "time.sleep(20)\n")
        process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.stdin.write(json.dumps({"original_request": {"request_kind":"smaller"}, "candidate": {"status":"need_info"}}).encode())
        process.stdin.close()
        limit = time.monotonic() + 3
        while len(list(marker.iterdir())) < 1 and time.monotonic() < limit:
            time.sleep(.01)
        pids = [int(path.name) for path in marker.iterdir()]
        self.assertEqual(len(pids), 1)
        process.kill()
        process.wait(timeout=2)
        process.stdout.close()
        process.stderr.close()
        records = self.root / "records"
        while not list(records.glob("*.json")) and time.monotonic() < limit:
            time.sleep(.01)
        record = json.loads(next(records.glob("*.json")).read_text())
        self.assertEqual(record["error"], "cancelled")
        self.assertTrue(record["process_reaped"])
        self.assertFalse(record["process_group_alive"])
        self.assertEqual(record["provider_messages"], 0)
        for pid in pids:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_inherited_parent_is_not_captured_after_parent_death(self):
        owner = os.getppid()
        cancelled = bridge.ParentCancelled(owner)
        self.assertFalse(cancelled.is_set())
        with patch.object(bridge.os, "getppid", return_value=1):
            self.assertTrue(cancelled.is_set())


if __name__ == "__main__":
    unittest.main()

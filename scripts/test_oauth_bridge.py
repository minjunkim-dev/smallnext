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
            "assert '--json-schema' not in sys.argv\n"
            "assert sys.argv[sys.argv.index('--effort')+1]=='xhigh'\n"
            "assert sys.argv[sys.argv.index('--model')+1]=='claude-haiku-5-5'\n"
            "print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))\n"
            "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
            "'modelUsage':{'claude-haiku-5-5':{}},'result':json.dumps({'ok':True})}))\n")
        self.fake.chmod(0o700)
        self.command = [sys.executable, str(Path(bridge.__file__)), "--claude", str(self.fake),
                        "--records", str(self.root / "records"), "--output-schema", str(self.schema),
                        "-c", "model_instructions_file=" + json.dumps(str(self.prompt))]

    def invoke(self):
        return subprocess.run(self.command, input="{}", text=True, capture_output=True, timeout=5)

    def test_default_single_json_reaches_rust_event_parser(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(events[-1], {"type": "turn.completed"})
        self.assertEqual(json.loads(events[0]["item"]["text"]), {"ok": True})
        record = json.loads(next((self.root / "records").glob("*.json")).read_text())
        self.assertEqual(record["output_mode"], "text-json")
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

    def test_adapter_kill_reaps_claude_without_parent_handler(self):
        marker = self.root / "pid"
        self.fake.write_text("#!/usr/bin/env python3\nimport os,time\n"
                            + f"open({str(marker)!r},'w').write(str(os.getpid()))\n"
                            + "time.sleep(20)\n")
        process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.stdin.write(b"{}")
        process.stdin.close()
        limit = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < limit:
            time.sleep(.01)
        self.assertTrue(marker.exists())
        pid = int(marker.read_text())
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

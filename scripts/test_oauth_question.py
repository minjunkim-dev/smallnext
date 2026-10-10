"""Question specialization keeps all five semantic checks and strict output guards."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import oauth_quality as qa


class QuestionCheckTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((qa.REPO / "services/api/src/development_ai/check.json").read_text())
        self.contract = (qa.REPO / "services/api/src/development_ai/contract.md").read_text()
        self.prompt = (qa.REPO / "services/api/src/development_ai/check.md").read_text()+"\n"+self.contract
        fixture = json.loads((qa.REPO / "docs/research/fixtures/checker-latency-checks.json").read_text())
        self.data = {"original_request":fixture["original_request"], "candidate":fixture["cases"][0]["candidate"]}

    def test_projection_keeps_every_criterion_and_normative_section(self):
        question = qa.question_prompt(self.prompt)
        self.assertNotEqual(question, self.prompt)
        paragraphs = self.contract.split("\n\n")
        for index, paragraph in enumerate(paragraphs):
            if index != 4:
                self.assertIn(paragraph, question)
        for line in paragraphs[4].splitlines()[2:6]:
            self.assertIn(line, question)
        self.assertIn("For accept, return exactly criteria [1,2,3,4,5]", question)
        for changed in (self.prompt+"\n\nNew normative rule", self.prompt.replace("- no_action uses", "- new rule"),
                        self.prompt.replace("Status selection:", "Unrecognized section:")):
            self.assertEqual(qa.question_prompt(changed), changed)

    def test_only_smaller_question_is_specialized_without_extra_call_or_payload_change(self):
        for kind, status in (("smaller","need_info"),("replacement","need_info"),("smaller","action"),
                             ("goal_preparation","need_info"),(None,"need_info")):
            with self.subTest(kind=kind, status=status):
                data = json.loads(json.dumps(self.data))
                data["original_request"]["request_kind"] = kind
                data["candidate"]["status"] = status
                before = qa.encoded(data)
                with patch.object(qa, "_call", return_value={"error":"cancelled"}) as single:
                    qa.call("claude", self.prompt, self.schema, data, qa.monotonic()+2, threading.Event())
                single.assert_called_once()
                self.assertEqual(single.call_args.args[1] != self.prompt, kind=="smaller" and status=="need_info")
                self.assertEqual(qa.encoded(data), before)
        with patch.object(qa, "_call", return_value={"error":"cancelled"}) as single:
            qa.call("claude", self.prompt, {"properties":{"ok":{"type":"boolean"}}}, self.data,
                    qa.monotonic()+2, threading.Event())
        self.assertEqual(single.call_args.args[1], self.prompt)

    def test_incomplete_accept_or_blank_evidence_is_not_repaired_or_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory)/"claude"
            for verdict, criteria, evidence, fields in (
                    ("accept",[4],"PRIVATE",["criteria"]),
                    ("accept",[1,2,3,4,5],"",["evidence","reason"]),
                    ("reject",[4],"source quote",None),
                    ("uncertain",[4],"source quote",None)):
                with self.subTest(verdict=verdict, criteria=criteria, fields=fields):
                    out = {"verdict":verdict,"criteria":criteria,"evidence":evidence}
                    fake.write_text("#!/usr/bin/env python3\nimport json\n"
                        "print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))\n"
                        "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
                        "'modelUsage':{'claude-haiku-5-5':{}},'structured_output':"+repr(out)+"}))\n")
                    fake.chmod(0o700)
                    record = qa.call(str(fake),self.prompt,self.schema,self.data,qa.monotonic()+2,threading.Event())
                    if fields:
                        self.assertEqual(record["error"], "invalid_check")
                        self.assertEqual(record["invalid_check_fields"], fields)
                        self.assertNotIn("output",record)
                        self.assertNotIn("PRIVATE",json.dumps(record))
                    else:
                        self.assertEqual(record["output"]["verdict"],verdict)
                        self.assertEqual(record["output"]["criteria"],criteria)
                    self.assertTrue(record["process_reaped"])
                    self.assertFalse(record["process_group_alive"])


if __name__ == "__main__":
    unittest.main()

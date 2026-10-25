"""The OAuth evaluator replays the Rust compact contract pinned in one shared fixture."""
import json
from pathlib import Path
import tempfile
import unittest

import oauth_quality as qa


class CompactContractParityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((qa.REPO / "contracts/fixtures/suggestion-compact.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory) / "frozen"
            qa.freeze(frozen, "quality", sequential=True)
            self.manifest = json.loads((frozen / "manifest.json").read_text())

    def test_prompts_and_schemas_match_rust(self):
        for index, case in enumerate(self.fixture["cases"]):
            with self.subTest(index=index, role=case["role"], prompt=case["prompt"]):
                payload = case["payload"]
                if case["role"] == "generate":
                    schema = qa.schema_for(self.manifest, payload)
                else:
                    schema = self.manifest["schemas"]["check"]
                prompt, schema = qa.request(self.manifest["prompts"][case["role"]], schema, payload)
                self.assertEqual(prompt, self.fixture["prompts"][case["prompt"]])
                self.assertEqual(schema, self.fixture["schemas"][case["schema"]])

    def test_generation_reduction_instructions_are_status_scoped_and_grounded(self):
        fixture = json.loads((qa.REPO / "contracts/fixtures/insufficient-info.json").read_text())
        for kind in ("first_action", "next_action", "smaller", "replacement"):
            payload = dict(fixture["input"], request_kind=kind)
            compact, _ = qa.request(self.manifest["prompts"]["generate"],
                                    qa.schema_for(self.manifest, payload), payload)
            for prompt in (self.manifest["prompts"]["generate"], compact):
                with self.subTest(kind=kind, compact=prompt == compact):
                    self.assertTrue('Outside smaller action/minimum, set reduction to "" for insufficient_info' in prompt,
                                    'missing status-scoped reduction default')
                    self.assertTrue('and to "해당 없음" for every other status.' in prompt, 'missing other-status default')
                    self.assertFalse('Otherwise set reduction to "해당 없음".' in prompt, 'unscoped default conflicts with notice')
                    self.assertTrue('do not add unsupported quantities, steps or results' in prompt, 'missing prior-work grounding')
            # Replay the malformed pattern without weakening validation or repairing output.
            malformed = dict(fixture["generated"], reduction="해당 없음")
            self.assertEqual(qa.proposal_invalid_fields(payload, malformed), ["reduction"])
            self.assertTrue(qa.proposal_valid(payload, fixture["generated"]))

    def test_status_table_matches_rust(self):
        for kind, allowed in self.fixture["statuses"].items():
            with self.subTest(kind=kind):
                original = {"request_kind": None if kind == "none" else kind}
                self.assertEqual(qa.schema_for(self.manifest, original)["properties"]["status"]["enum"], allowed)



class InsufficientInfoFormatTests(unittest.TestCase):
    def test_source_work_states_keep_the_approved_reference_and_grounded_evidence(self):
        fixture = json.loads((qa.REPO / "contracts/fixtures/insufficient-info.json").read_text())
        cases = {case["id"]: case for case in fixture["checker_cases"]}
        for ident, verdict in (("useful-source-check", "reject"),
                               ("conflicting-sources", "reject"),
                               ("source-omission-is-not-absence", "accept")):
            with self.subTest(case=ident):
                case = cases[ident]
                self.assertEqual(case["check"]["verdict"], verdict)
                self.assertTrue(qa.proposal_valid(case["input"], fixture["generated"]))
                self.assertIn(case["check"]["evidence"],
                              "\n".join([case["input"]["current_blocker"], *case["input"]["available"]]))

    def test_shared_notice_fields_and_request_kind_schema(self):
        fixture = json.loads((qa.REPO / "contracts/fixtures/insufficient-info.json").read_text())
        original, candidate = fixture["input"], fixture["generated"]
        self.assertTrue(qa.proposal_valid(original, candidate))
        for kind in [None, "goal_preparation", "unsupported"]:
            with self.subTest(kind=kind):
                self.assertFalse(qa.proposal_valid(dict(original, request_kind=kind), candidate))
        for field, value in [("action", "가짜 행동"), ("completion_condition", " "),
                             ("estimated_minutes", 1), ("reason", " "), ("reduction", "해당 없음")]:
            with self.subTest(field=field):
                self.assertFalse(qa.proposal_valid(original, dict(candidate, **{field: value})))


if __name__ == "__main__":
    unittest.main()

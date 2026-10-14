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

    def test_status_table_matches_rust(self):
        for kind, allowed in self.fixture["statuses"].items():
            with self.subTest(kind=kind):
                original = {"request_kind": None if kind == "none" else kind}
                self.assertEqual(qa.schema_for(self.manifest, original)["properties"]["status"]["enum"], allowed)


if __name__ == "__main__":
    unittest.main()

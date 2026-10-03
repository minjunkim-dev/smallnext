import json
import unittest

from review_failure import summarize


class ReviewFailureTest(unittest.TestCase):
    def test_authentication_report_never_contains_the_token(self):
        messages = [{"type": "result", "subtype": "success", "num_turns": 1,
                     "result": "Authentication failed for secret-example-token"}]
        report = summarize(messages)
        self.assertEqual(report["category"], "authentication")
        self.assertNotIn("secret-example-token", json.dumps(report))

    def test_transcript_does_not_determine_failure_category(self):
        messages = [{"type": "assistant", "message": "Authentication failed: private-token"},
                    {"type": "result", "subtype": "error_max_turns", "errors": ["Reached max turns"]}]
        self.assertEqual(summarize(messages)["category"], "turn_limit")

    def test_unknown_metadata_is_not_echoed(self):
        report = summarize([{"type": "result", "subtype": "private-token", "num_turns": "private-token"}])
        self.assertNotIn("private-token", json.dumps(report))
        self.assertEqual(report["subtype"], "unknown")

    def test_quota_and_missing_result(self):
        self.assertEqual(summarize([{"type": "result", "result": "Credit balance is too low"}])["category"], "quota")
        self.assertEqual(summarize({"unexpected": "private-token"})["category"], "unavailable")


if __name__ == "__main__":
    unittest.main()

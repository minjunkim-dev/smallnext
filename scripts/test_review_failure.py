import json
import unittest

from review_failure import summarize


class ReviewFailureTest(unittest.TestCase):
    def test_authentication_report_never_contains_the_token(self):
        messages = [{"type": "assistant", "error": "authentication_failed",
                     "message": "secret-example-token"},
                    {"type": "result", "subtype": "success", "num_turns": 1, "is_error": True,
                     "result": "Authentication failed for secret-example-token"}]
        report = summarize(messages)
        self.assertEqual(report["category"], "authentication")
        self.assertNotIn("secret-example-token", json.dumps(report))

    def test_transcript_does_not_determine_failure_category(self):
        messages = [{"type": "assistant", "message": "Authentication failed: private-token"},
                    {"type": "result", "subtype": "error_max_turns", "errors": ["Reached max turns"]}]
        self.assertEqual(summarize(messages)["category"], "turn_limit")

    def test_unknown_metadata_is_not_echoed(self):
        report = summarize([{"type": "assistant", "error": "private-token"},
                            {"type": "result", "subtype": ["private-token"], "is_error": True,
                             "num_turns": "private-token", "api_error_status": "private-token"}])
        self.assertNotIn("private-token", json.dumps(report))
        self.assertEqual(report["subtype"], "unknown")

    def test_quota_and_missing_result(self):
        self.assertEqual(summarize([{"type": "result", "subtype": "error_max_budget_usd"}])["category"], "quota")
        self.assertEqual(summarize({"unexpected": "private-token"})["category"], "unavailable")

    def test_model_prose_and_free_form_errors_do_not_classify_failure(self):
        for subtype in ("success", "error_max_turns"):
            report = summarize([{"type": "result", "subtype": subtype, "is_error": True,
                                 "result": "Authentication 401 quota", "errors": ["Authentication 401"]}])
            self.assertEqual(report["category"], "turn_limit" if subtype == "error_max_turns" else "unknown")

    def test_only_terminal_assistant_error_can_classify_failure(self):
        messages = [{"type": "assistant", "error": "authentication_failed"},
                    {"type": "assistant", "message": "Recovered"},
                    {"type": "result", "subtype": "success", "is_error": True},
                    {"type": "assistant", "error": "authentication_failed"}]
        self.assertEqual(summarize(messages)["category"], "unknown")

    def test_successful_result_ignores_prior_errors_and_api_status(self):
        report = summarize([{"type": "assistant", "error": "authentication_failed"},
                            {"type": "result", "subtype": "success", "is_error": False, "api_error_status": 401}])
        self.assertEqual(report["category"], "unknown")

    def test_structured_http_status_and_sdk_error_are_reported(self):
        report = summarize([{"type": "assistant", "error": "invalid_request"},
                            {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 401}])
        self.assertEqual(report["category"], "authentication")
        self.assertEqual(report["api_status"], 401)


if __name__ == "__main__":
    unittest.main()

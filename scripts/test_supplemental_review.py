"""Synthetic integration at the existing fixed-plan execution/report seam."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

import launch_evaluation as launch
import oauth_quality as qa
import test_launch_evaluation as legacy
import test_supplemental_fixed_plan as fixed


class SupplementalReviewTests(unittest.TestCase):
    freeze = fixed.SupplementalFixedPlanTests.freeze
    response = staticmethod(fixed.SupplementalFixedPlanTests.response)

    def setUp(self):
        legacy.isolate_private_root(self)

    def test_full_mock_plan_has_one_private_link_per_output_and_incomplete_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            summary = launch.run(root, invoke=self.response, clock=lambda: 0)
            review = summary['output_review']
            self.assertEqual(len(review['items']), 123)
            self.assertEqual(len({item['output_id'] for item in review['items']}), 123)
            self.assertEqual(review['state'], 'awaiting_human_review')
            self.assertFalse(review['work_complete'])
            self.assertEqual(review['contract_fit'], 'deferred')
            self.assertFalse(summary['preparation']['ready'])
            self.assertEqual(summary['preparation']['output_tokens'], 8192)
            self.assertEqual(summary['plan_sha256'], manifest['plan_sha256'])
            for item in review['items']:
                self.assertIsNone(item['human_decision'])
                self.assertIsNone(item['human_reason_sha256'])
                raw = json.loads((root/item['result_file']).read_bytes())
                self.assertEqual(item['record_sha256'], qa.digest((root/item['result_file']).read_bytes()))
                call = raw['calls'][item['call_index']]
                self.assertEqual(item['output_sha256'], qa.digest(qa.encoded(call['output'])))
                self.assertEqual(item['input_sha256'], call['input_sha256'])
                self.assertEqual(item['request_id'], raw['request_id'])
                self.assertEqual(item['requested_model'], qa.MODEL)
                self.assertIsNone(item['observed_effort'])
            self.assertEqual(launch.report(root), summary)
            public = json.dumps(summary, ensure_ascii=False)
            self.assertNotIn('참여자 세 명의 일정을 조율', public)
            self.assertNotIn(str(root), public)
            self.assertIsNone(summary['quality_passed'])

    @staticmethod
    def decisions(summary):
        review = deepcopy(summary['output_review']['template'])
        review['basis'] = 'synthetic'
        for entry in review['entries']:
            entry.update(decision='meets_expectation', reason='PRIVATE synthetic judgement')
        return review

    def test_mock_review_completion_findings_and_uncertainty_are_separate_from_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            original = launch.run(root, invoke=self.response, clock=lambda: 0)
            review = self.decisions(original)
            partial = dict(review, entries=review['entries'][:1])
            self.assertFalse(launch.report(root, review=partial)['output_review']['work_complete'])
            complete = launch.report(root, review=review)
            self.assertEqual(complete['output_review']['state'], 'synthetic_work_complete')
            self.assertTrue(complete['output_review']['work_complete'])
            self.assertEqual(complete['output_review']['contract_fit'], 'deferred')
            with patch.object(qa, 'output_readiness', return_value=dict(ready=True, output_tokens=8192,
                    evidence_sha256=manifest['sources']['docs/research/claude-output-limit-support.json']['sha256'])):
                simulated = launch.report(root, review=review)
            self.assertEqual(simulated['output_review']['contract_fit'], 'synthetic_fit')
            self.assertFalse(simulated['preparation']['actual_execution_authorized'])
            self.assertIsNone(simulated['quality_passed'])
            generated = next(entry for entry in review['entries'] if entry['output_id'].endswith(':generate'))
            generated['decision'] = 'generation_violation'
            review['entries'][0]['decision'] = 'checker_misjudgement'
            review['entries'][1]['decision'] = 'uncertain'
            assessed = launch.report(root, review=review)
            self.assertTrue(assessed['output_review']['problem_found'])
            self.assertEqual(len(assessed['output_review']['problem_outputs']), 2)
            self.assertTrue(assessed['output_review']['deferred_scopes'])
            self.assertTrue(assessed['output_review']['work_complete'])
            self.assertNotIn('PRIVATE', json.dumps(assessed))
            self.assertEqual(assessed['human_review'], 'not_performed')
            self.assertEqual(launch.report(root)['output_review']['state'], 'awaiting_human_review')

    def test_review_rejects_duplicate_unrelated_changed_or_unexplained_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            summary = launch.run(root, invoke=self.response, clock=lambda: 0)
            valid = self.decisions(summary)
            for fault in ('duplicate', 'unrelated', 'hash', 'empty_reason', 'manifest', 'role'):
                review = deepcopy(valid)
                if fault == 'duplicate':
                    review['entries'][1] = deepcopy(review['entries'][0])
                elif fault == 'unrelated':
                    review['entries'][0]['output_id'] = 'PRIVATE'
                elif fault == 'hash':
                    review['entries'][0]['output_sha256'] = '0'*64
                elif fault == 'empty_reason':
                    review['entries'][0]['reason'] = ' '
                elif fault == 'manifest':
                    review['manifest_sha256'] = '0'*64
                else:
                    review['entries'][0]['decision'] = 'generation_violation'
                with self.subTest(fault=fault), self.assertRaises(ValueError):
                    launch.report(root, review=review)

    def test_injected_output_limit_violation_stops_whole_plan(self):
        for tokens, error in ((8193, 'output_tokens_exceeded'), (30.5, 'unverified_output_usage'),
                              (None, 'usage_unknown')):
            with self.subTest(tokens=tokens), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                received = []

                def invoke(*args):
                    received.append(args[0])
                    result = self.response(*args)
                    result['usage']['output_tokens'] = tokens
                    return result

                summary = launch.run(root, invoke=invoke, clock=lambda: 0)
                self.assertEqual(received, ['check'])
                self.assertEqual(summary['stop_reason'], error)
                self.assertEqual(summary['units'][1]['state'], 'not_executed')
                self.assertEqual(summary['output_review']['items'][0]['output_tokens'], tokens)

    def test_technical_errors_and_cancellation_preserve_all_unexecuted_units(self):
        for error in ('cancelled', 'timed_out', 'max_tokens', 'provider_retry', 'process_cleanup'):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                received = []

                def invoke(*args):
                    received.append(args[0])
                    result = self.response(*args)
                    result.pop('output')
                    result['error'] = error
                    return result

                summary = launch.run(root, invoke=invoke, clock=lambda: 0)
                self.assertEqual(received, ['check'])
                self.assertEqual(summary['stop_reason'], error)
                self.assertEqual(len(summary['units']), 75)
                self.assertEqual(summary['role_counts']['generate']['not_executed'], 48)
                self.assertEqual(summary['role_counts']['check']['not_executed'], 74)
                self.assertTrue(all(unit['reason'] for unit in summary['units']))
                self.assertFalse(summary['output_review']['work_complete'])
                review = self.decisions(summary)
                complete = launch.report(root, review=review)['output_review']
                self.assertTrue(complete['work_complete'])
                self.assertEqual(complete['contract_fit'], 'deferred')
                self.assertFalse(complete['problem_found'])

    def test_initial_and_rerequest_mismatch_do_not_become_human_findings(self):
        for check_number in (10, 11):
            with self.subTest(check_number=check_number), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                checks = [0]

                def invoke(*args):
                    result = self.response(*args)
                    if args[0] == 'check':
                        checks[0] += 1
                        if checks[0] == check_number:
                            result['output']['verdict'] = 'reject'
                    return result

                summary = launch.run(root, invoke=invoke, clock=lambda: 0)
                self.assertEqual(summary['reference_mismatches'], 1)
                self.assertEqual(len(summary['output_review']['items']), 121 if check_number == 10 else 123)
                self.assertEqual(summary['units'][10]['reason'], 'initial_semantic_failure' if check_number == 10 else 'unexpected_quality')
                self.assertFalse(summary['output_review']['problem_found'])
                assessed = launch.report(root, review=self.decisions(summary))
                self.assertTrue(assessed['output_review']['work_complete'])
                self.assertEqual(assessed['output_review']['contract_fit'], 'deferred')
                self.assertEqual(summary['units'][-1]['state'], 'completed')

    def test_retention_uses_earlier_frozen_limit_without_rewrite_or_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            deadline = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
            manifest['retention']['delete_by'] = deadline
            manifest['plan_sha256'] = launch.supplemental.binding(manifest)
            (root/'manifest.json').write_bytes(qa.encoded(manifest))
            (root/'integrity.json').write_bytes(qa.encoded({'manifest_sha256':qa.digest(qa.encoded(manifest))}))
            summary = launch.run(root, invoke=self.response, clock=lambda: 0)
            before = {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for _ in range(2):
                self.assertEqual(launch.report(root)['retention']['delete_by'], deadline)
            self.assertEqual(before, {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertFalse(summary['retention']['extended_by_report'])
            ended = json.loads((root/'run-ended.json').read_bytes())
            ended['delete_by'] = (datetime.fromisoformat(deadline) + timedelta(days=1)).isoformat()
            (root/'run-ended.json').write_bytes(qa.encoded(ended))
            with self.assertRaisesRegex(ValueError, 'retention deadline extended'):
                launch.report(root)

    def test_missing_changed_support_and_actual_run_stay_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response, clock=lambda: 0)
            support = Path(directory)/'support.json'
            for missing in (True, False):
                if not missing:
                    support.write_text('{"ready":true,"PRIVATE":"secret"}')
                with self.subTest(missing=missing), patch.object(qa, 'OUTPUT_SUPPORT', support):
                    report = launch.report(root)
                    self.assertFalse(report['preparation']['ready'])
                    self.assertIn('support_missing' if missing else 'support_changed', report['preparation']['reasons'])
                    self.assertNotIn('PRIVATE', json.dumps(report))
            with patch.object(launch, 'subscription_account') as auth, patch.object(qa.subprocess, 'Popen') as child:
                with self.assertRaisesRegex(ValueError, 'actual evaluation remains blocked'):
                    launch.run(root, claude='must-not-start')
                auth.assert_not_called()
                child.assert_not_called()

    def test_fake_cli_cap_stop_is_reaped_and_unknown_usage_stays_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            fake = Path(directory)/'claude'
            fake.write_text('#!' + sys.executable + '\n' + '''import json,os,sys
assert os.environ['CLAUDE_CODE_MAX_OUTPUT_TOKENS']=='8192'
json.load(sys.stdin)
print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}),flush=True)
print(json.dumps({'type':'stream_event','event':{'type':'message_delta','delta':{'stop_reason':'max_tokens'}}}),flush=True)
''')
            fake.chmod(0o700)

            def invoke(role, prompt, schema, data, deadline, cancelled):
                with patch.object(qa, 'output_readiness', return_value={'ready':True}):
                    return qa.call(str(fake), prompt, schema, data, deadline, cancelled, output_mode='text-json')

            summary = launch.run(root, invoke=invoke)
            self.assertEqual(summary['stop_reason'], 'max_tokens')
            self.assertEqual(summary['roles']['started'], 1)
            self.assertEqual(summary['role_usage']['check']['output_tokens']['unknown_calls'], 1)
            row = json.loads((root/'results/000.json').read_bytes())
            self.assertTrue(row['calls'][0]['process_reaped'])
            self.assertFalse(row['calls'][0]['process_group_alive'])
            self.assertIsNone(row['calls'][0]['usage']['output_tokens'])
            self.assertFalse(summary['preparation']['ready'])

    def test_fake_cli_success_keeps_normalized_token_usage_and_review_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            fake = Path(directory)/'claude'
            called = [0]

            def invoke(role, prompt, schema, data, deadline, cancelled):
                called[0] += 1
                result = self.response(role, prompt, schema, data, deadline, cancelled)
                if called[0] > 1:
                    result.pop('output')
                    return dict(result, error='cancelled')
                out = result['output']
                out.pop('reason')
                events = [{'type':'stream_event','event':{'type':'message_start'}},
                          {'type':'result','subtype':'success','is_error':False,
                           'modelUsage':{qa.MODEL:{}},'usage':{'input_tokens':100,'output_tokens':30},
                           'result':json.dumps(out)}]
                fake.write_text('#!' + sys.executable + '\nimport json,sys\njson.load(sys.stdin)\n' +
                    '\n'.join('print(' + repr(json.dumps(event)) + ')' for event in events))
                fake.chmod(0o700)
                with patch.object(qa, 'output_readiness', return_value={'ready':True}):
                    return qa.call(str(fake), prompt, schema, data, deadline, cancelled, output_mode='text-json')

            summary = launch.run(root, invoke=invoke)
            self.assertEqual(called[0], 2)
            self.assertEqual(summary['stop_reason'], 'cancelled')
            self.assertEqual(len(summary['output_review']['items']), 1)
            item = summary['output_review']['items'][0]
            self.assertEqual(item['output_tokens'], 30)
            self.assertEqual(item['configuration_delivery'], 'transport_reported')

    def test_missing_or_duplicate_result_never_finishes_review_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response, clock=lambda: 0)
            first = (root/'results/000.json').read_bytes()
            for fault in ('missing', 'duplicate'):
                with self.subTest(fault=fault):
                    if fault == 'missing':
                        (root/'results/000.json').unlink()
                    else:
                        (root/'results/000.json').write_bytes(first)
                        (root/'results/duplicate.json').write_bytes(first)
                    summary = launch.report(root)
                    reviewed = launch.report(root, review=self.decisions(summary))
                    self.assertFalse(reviewed['output_review']['work_complete'])
                    self.assertEqual(reviewed['output_review']['contract_fit'], 'deferred')

    def test_changed_or_missing_required_plan_blocks_before_injected_transport(self):
        for fault in ('model', 'effort', 'output_token_limit', 'support', 'review_source'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root, manifest = self.freeze(directory)
                if fault == 'support':
                    manifest['sources'].pop('docs/research/claude-output-limit-support.json')
                elif fault == 'review_source':
                    manifest['sources'].pop('scripts/supplemental_review.py')
                elif fault == 'output_token_limit':
                    manifest.pop(fault)
                else:
                    manifest[fault] = 'PRIVATE'
                manifest['plan_sha256'] = launch.supplemental.binding(manifest)
                (root/'manifest.json').write_bytes(qa.encoded(manifest))
                (root/'integrity.json').write_bytes(qa.encoded({'manifest_sha256':qa.digest(qa.encoded(manifest))}))
                with patch.object(self, 'response') as invoke:
                    with self.assertRaises(ValueError):
                        launch.run(root, invoke=invoke)
                    invoke.assert_not_called()
                self.assertFalse((root/'run-started.json').exists())

    def test_cli_reads_private_review_without_model_calls_or_reason_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            summary = launch.run(root, invoke=self.response, clock=lambda: 0)
            review = root/'judgements.json'
            review.write_bytes(qa.encoded(self.decisions(summary)))
            command = [sys.executable, str(Path(launch.__file__)), 'report', str(root),
                       '--review', str(review), '--output', 'review-report.json']
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report['output_review']['work_complete'])
            self.assertFalse(report['preparation']['ready'])
            self.assertNotIn('PRIVATE', result.stdout)
            self.assertEqual(json.loads((root/'review-report.json').read_bytes()), report)


if __name__ == '__main__':
    unittest.main()

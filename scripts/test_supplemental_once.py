"""Synthetic single-repeat plans and bounded direct-human review; no real model calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import launch_evaluation as launch
import oauth_quality as qa
import test_launch_evaluation as legacy
import test_supplemental_fixed_plan as fixed


class SingleRepeatTests(unittest.TestCase):
    def setUp(self):
        legacy.isolate_private_root(self)

    def freeze(self, directory):
        root = Path(directory).resolve()/'once'
        launch.freeze(root, owner='synthetic-owner', ends_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
            delete_method='delete temporary synthetic bundle', plan_kind='supplemental-once',
            flows=launch.supplemental.fixed_flows(once=True))
        return root, launch.load(root)

    @staticmethod
    def agent(summary, basis='declared_agent'):
        result = deepcopy(summary['first_pass_review']['template'])
        result['basis'] = basis
        for item in result['entries']:
            item.update(decision='meets_expectation', reason='PRIVATE agent review')
        return result

    @staticmethod
    def human(summary, basis='declared_human'):
        result = deepcopy(summary['comparison_review']['template'])
        result['basis'] = basis
        for item in result['entries']:
            item.update(decision='meets_expectation', reason='PRIVATE direct human review')
        return result

    def test_one_repeat_counts_pairing_and_execution_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            self.assertEqual(manifest['version'], 4)
            self.assertEqual(manifest['plan_id'], 'supplemental-once-v1')
            self.assertEqual(launch.validate_supplemental(manifest), dict(units=25, generate=16, check=25, roles=41))
            self.assertEqual(manifest['limits'], launch.ONCE_LIMITS)
            self.assertEqual({f['repeat'] for f in manifest['flows']}, {1})
            summary = launch.run(root, invoke=fixed.SupplementalFixedPlanTests.response, clock=lambda: 0)
            self.assertEqual(summary['roles']['started'], 41)
            self.assertEqual(len(summary['first_pass_review']['items']), 41)
            self.assertEqual(len(summary['comparison_review']['cards']), 8)
            self.assertFalse(summary['comparison_review']['work_complete'])
            private = launch.report(root, comparisons=True)['private_comparisons']
            self.assertEqual(len(private['cards']), 8)
            for card in private['cards']:
                self.assertEqual([phase['phase'] for phase in card['phases']], ['initial', 'explicit_rerequest'])
                self.assertEqual(card['phases'][0]['input']['request_kind'], card['phases'][1]['input']['request_kind'])
                self.assertNotEqual(card['phases'][0]['input'], card['phases'][1]['input'])
            self.assertNotIn('참여자 세 명의 일정을 조율', json.dumps(summary, ensure_ascii=False))
            self.assertFalse(summary['preparation']['actual_execution_authorized'])
            self.assertIsNone(summary['quality_passed'])
            with patch.object(launch, 'subscription_account') as auth, patch.object(qa.subprocess, 'Popen') as child:
                with self.assertRaisesRegex(ValueError, 'actual evaluation remains blocked'):
                    launch.run(root, claude='must-not-start')
                auth.assert_not_called(); child.assert_not_called()

    def test_agent_and_eight_human_decisions_are_separate_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            initial = launch.run(root, invoke=fixed.SupplementalFixedPlanTests.response, clock=lambda: 0)
            agent = self.agent(initial)
            first = launch.report(root, review=dict(first_pass=agent, human=None))
            self.assertTrue(first['first_pass_review']['work_complete'])
            self.assertEqual(first['first_pass_review']['state'], 'agent_review_complete')
            self.assertFalse(first['comparison_review']['human_complete'])
            self.assertNotIn('human_decision', first['first_pass_review']['items'][0])
            human = self.human(first)
            done = launch.report(root, review=dict(first_pass=agent, human=human))
            self.assertTrue(done['comparison_review']['work_complete'])
            self.assertEqual(done['comparison_review']['contract_fit'], 'declared_fit')
            self.assertEqual(done['human_review'], 'not_performed')  # legacy blanket review is never asserted
            self.assertFalse(done['preparation']['actual_execution_authorized'])
            self.assertNotIn('PRIVATE', json.dumps(done))
            for fault in ('missing', 'duplicate', 'hash', 'run', 'reason'):
                changed = deepcopy(human)
                if fault == 'missing': changed['entries'].pop()
                elif fault == 'duplicate': changed['entries'][1] = changed['entries'][0]
                elif fault == 'hash': changed['entries'][0]['card_sha256'] = '0'*64
                elif fault == 'run': changed['run_id'] = 'other'
                else: changed['entries'][0]['reason'] = ''
                with self.subTest(fault=fault):
                    if fault == 'missing':
                        self.assertFalse(launch.report(root, review=dict(first_pass=agent, human=changed))['comparison_review']['work_complete'])
                    else:
                        with self.assertRaises(ValueError): launch.report(root, review=dict(first_pass=agent, human=changed))
            changed = deepcopy(agent)
            next(item for item in changed['entries'] if item['output_id'].endswith(':generate'))['reason'] = 'different first pass'
            with self.assertRaisesRegex(ValueError, 'changed'):
                launch.report(root, review=dict(first_pass=changed, human=human))
            wrong = dict(agent, basis='declared_human')
            with self.assertRaises(ValueError): launch.report(root, review=dict(first_pass=wrong, human=None))
            partial = dict(agent, entries=agent['entries'][:-1])
            self.assertFalse(launch.report(root, review=dict(first_pass=partial, human=None))['first_pass_review']['work_complete'])

    def test_fixed_checker_anomaly_requires_an_extra_human_card(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            initial = launch.run(root, invoke=fixed.SupplementalFixedPlanTests.response, clock=lambda: 0)
            agent = self.agent(initial)
            agent['entries'][0]['decision'] = 'checker_misjudgement'
            flagged = launch.report(root, review=dict(first_pass=agent, human=None))
            cards = flagged['comparison_review']['cards']
            self.assertEqual(len(cards), 9)
            anomaly = next(c for c in cards if c['kind'] == 'anomaly')
            self.assertIn('checker_misjudgement', anomaly['anomalies'])
            human = self.human(flagged)
            human['entries'] = [e for e in human['entries'] if e['card_id'] != anomaly['card_id']]
            self.assertFalse(launch.report(root, review=dict(first_pass=agent, human=human))['comparison_review']['human_complete'])
            human = self.human(flagged)
            reviewed = launch.report(root, review=dict(first_pass=agent, human=human))
            self.assertTrue(reviewed['comparison_review']['work_complete'])
            self.assertEqual(reviewed['comparison_review']['contract_fit'], 'deferred')

    def test_synthetic_review_never_becomes_direct_human_fit(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            initial = launch.run(root, invoke=fixed.SupplementalFixedPlanTests.response, clock=lambda: 0)
            agent = self.agent(initial, 'synthetic')
            first = launch.report(root, review=dict(first_pass=agent, human=None))
            done = launch.report(root, review=dict(first_pass=agent, human=self.human(first)))
            self.assertEqual(done['comparison_review']['contract_fit'], 'synthetic_fit')

    def test_technical_stop_preserves_missing_and_unexecuted_comparisons(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            summary = launch.run(root, invoke=lambda *args: dict(error='timed_out', seconds=1), clock=lambda: 0)
            self.assertEqual(summary['roles']['started'], 1)
            self.assertEqual(summary['stop_reason'], 'timed_out')
            self.assertEqual(len([c for c in summary['comparison_review']['cards'] if c['kind']=='comparison']), 8)
            self.assertTrue(all(c['anomalies'] for c in summary['comparison_review']['cards']))
            self.assertEqual(summary['comparison_review']['contract_fit'], 'deferred')
            self.assertFalse(summary['first_pass_review']['work_complete'])

    def test_role_41_is_single_check_and_larger_or_downgraded_plan_rejected(self):
        budget = launch.Budget({'limits':launch.ONCE_LIMITS}, lambda: 0)
        for _ in range(16):
            self.assertIsNone(budget.admit()); budget.start_role('generate'); budget.start_role('check')
        for _ in range(8):
            self.assertIsNone(budget.admit(('check',))); budget.start_role('check')
        self.assertEqual(budget.calls, 40)
        self.assertEqual(budget.admit(), 'call_limit')
        self.assertIsNone(budget.admit(('check',))); self.assertIsNone(budget.start_role('check'))
        self.assertEqual(budget.start_role('check'), 'call_limit')
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            for changes in (dict(version=3), dict(limits=launch.SUPPLEMENTAL_LIMITS),
                            dict(flows=launch.supplemental.fixed_flows())):
                changed = dict(deepcopy(manifest), **changes)
                changed['plan_sha256'] = launch.supplemental.binding(changed)
                with self.subTest(changes=changes.keys()), self.assertRaises(ValueError): launch.validate_supplemental(changed)

    def test_private_markdown_export_keeps_public_stdout_clean_and_refuses_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=fixed.SupplementalFixedPlanTests.response, clock=lambda: 0)
            command = [sys.executable, str(Path(launch.__file__)), 'report', str(root),
                       '--output','public.json','--comparisons','comparisons.md']
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('참여자 세 명의 일정을 조율', result.stdout)
            self.assertNotIn('private_comparisons', json.loads(result.stdout))
            content = (root/'comparisons.md').read_text()
            self.assertIn('참여자 세 명의 일정을 조율', content)
            self.assertIn('보충 전', content); self.assertIn('보충 후 재요청', content)
            self.assertEqual(sum(line.startswith('## ') for line in content.splitlines()), 8)
            self.assertEqual((root/'comparisons.md').stat().st_mode & 0o777, 0o600)
            again = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual((root/'comparisons.md').read_text(), content)
            command[-1] = '../escape.md'
            bad = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse((root.parent/'escape.md').exists())

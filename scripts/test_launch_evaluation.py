"""Offline regression at the frozen launch evaluator's execution/report boundary."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import launch_evaluation as launch
import oauth_quality as qa


class LaunchEvaluationTests(unittest.TestCase):
    def freeze(self, directory):
        root = Path(directory) / "launch"
        launch.freeze(root, owner="minjunkim-dev",
                      ends_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                      delete_method="delete this private directory")
        return root, launch.load(root)

    def test_freeze_separates_launch_groups_and_preserves_original_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            self.assertEqual(Counter(c['group'] for c in manifest['flows']),
                             {'fixed': 15, 'additional': 9, 'boundary': 9})
            self.assertEqual(manifest['limits']['requests'], 81)
            self.assertEqual(manifest['limits']['calls'], 162)
            self.assertEqual(manifest['regression']['cases'], 47)
            self.assertEqual((manifest['model'], manifest['effort']),
                             ('claude-haiku-5-5', 'xhigh'))
            for flow in manifest['flows']:
                if flow['group'] == 'additional':
                    self.assertEqual(flow['input']['request_kind'], 'first_action')
                    self.assertEqual(flow['input']['completed_ids'], [])
                    self.assertEqual(flow['input']['previous_proposals'], [])
                    self.assertNotIn('이미 완료한 행동', ' '.join(flow['input']['available']))
                    self.assertNotIn('보류한 행동', ' '.join(flow['input']['available']))
            with self.assertRaises(FileExistsError):
                self.freeze(directory)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    @staticmethod
    def response(role, prompt, schema, data, deadline, cancelled):
        if role == 'generate':
            output = {'status': 'need_info', 'action': '필요한 정보 하나를 확인한다.',
                      'completion_condition': '확인할 정보 하나가 표시된다.',
                      'estimated_minutes': 1, 'reason': '확인 전에는 진행하지 않는다.',
                      'remaining_work': data['remaining_work'],
                      'preserved_completed_ids': data['completed_ids'],
                      'goal_completed': False, 'current_action_completed': False}
        else:
            output = {'verdict': 'accept', 'criteria': [1, 2, 3, 4, 5],
                      'evidence': 'quote; fits', 'reason': 'quote; fits'}
        return {'output': output, 'actual_models': [qa.MODEL], 'seconds': 2,
                'provider_messages': 1, 'provider_retries': 0,
                'additional_provider_requests': 0, 'cost_estimate_micro_usd': 100,
                'usage': {'input_tokens': 100, 'output_tokens': 50,
                          'cache_read_input_tokens': None, 'cache_creation_input_tokens': None}}

    def test_run_stops_each_flow_at_question_without_fabricated_answers_or_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            received = []

            def invoke(role, *args):
                received.append((role, json.loads(json.dumps(args[2]))))
                return self.response(role, *args)

            report = launch.run(root, invoke=invoke, cancelled=threading.Event())
            self.assertEqual(report['requests']['started'], 33)
            self.assertEqual(report['roles']['completed'], 66)
            self.assertEqual(report['terminations'], {'need_info': 33})
            self.assertTrue(report['automatic_passed'])
            self.assertIsNone(report['quality_passed'])
            self.assertIsNone(report['timings']['first_action']['p90'])
            self.assertEqual(report['screen_missing'], 33)
            self.assertEqual(len(received), 66)
            self.assertNotIn('expected', received[0][1])
            self.assertEqual(received[0][1]['previous_proposals'], [])
            with self.assertRaises(FileExistsError):
                launch.run(root, invoke=invoke)
            self.assertEqual(len(received), 66)

    def test_request_and_role_limits_allow_exact_maximum_without_extra_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)

            def invoke(role, *args):
                result = self.response(role, *args)
                if role == 'generate' and not args[2].get('unknown'):
                    result['output']['status'] = 'action'
                return result

            summary = launch.run(root, invoke=invoke)
            self.assertEqual(summary['requests']['started'], 81)
            self.assertEqual(summary['roles']['started'], 162)
            self.assertTrue(summary['automatic_passed'])
            self.assertEqual(summary['costs']['actual_billing'], None)
            self.assertFalse(summary['paid_budget_verified'])

    def test_money_and_unknown_usage_stop_before_next_role_or_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)

            def invoke(role, *args):
                result = self.response(role, *args)
                result['cost_estimate_micro_usd'] = 20_000
                if role == 'generate' and not args[2].get('unknown'):
                    result['output']['status'] = 'action'
                return result

            summary = launch.run(root, invoke=invoke)
            self.assertEqual(summary['stop_reason'], 'initial_budget_limit')
            self.assertEqual(summary['roles']['started'], 150)
            self.assertEqual(summary['costs']['charged_micro_usd'], 3_000_000)
            self.assertTrue(summary['unexecuted_flows'])
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)

            def unknown(role, *args):
                result = self.response(role, *args)
                result['usage'] = {}
                result.pop('cost_estimate_micro_usd')
                return result

            summary = launch.run(root, invoke=unknown)
            self.assertEqual(summary['stop_reason'], 'usage_unknown')
            self.assertEqual(summary['roles']['started'], 1)
            self.assertEqual(summary['costs']['charged_micro_usd'], 20_000)
            self.assertEqual(summary['costs']['conservative_roles'], 1)

    def test_generation_failure_does_not_check_and_model_or_settlement_failure_stops(self):
        for fault, reason in [('generate', 'provider_failed'), ('model', 'model_or_call_count'),
                              ('cost', 'cost_overrun'), ('check', 'invalid_check')]:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                roles = []

                def invoke(role, *args):
                    roles.append(role)
                    result = self.response(role, *args)
                    if fault == 'generate':
                        result.pop('output')
                        result['error'] = 'provider_failed'
                    if fault == 'model':
                        result['actual_models'] = ['unexpected_model']
                    if fault == 'cost':
                        result['cost_estimate_micro_usd'] = 20_001
                    if fault == 'check' and role == 'check':
                        result['output']['criteria'] = [1, 2, 3, 4]
                    return result

                summary = launch.run(root, invoke=invoke)
                self.assertEqual(summary['stop_reason'], reason)
                self.assertEqual(roles, ['generate', 'check'] if fault == 'check' else ['generate'])
                self.assertFalse(summary['automatic_passed'])

    def test_independent_repeats_share_only_their_own_generated_proposals(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            inputs = []

            def invoke(role, *args):
                result = self.response(role, *args)
                if role == 'generate':
                    inputs.append(json.loads(json.dumps(args[2])))
                    if not args[2]['unknown']:
                        result['output']['status'] = 'action'
                return result

            launch.run(root, invoke=invoke)
            self.assertEqual([len(x['previous_proposals']) for x in inputs[:9]], [0, 1, 2, 0, 1, 2, 0, 1, 2])
            self.assertEqual([x['request_kind'] for x in inputs[:3]], ['first_action', 'smaller', 'smaller'])
            self.assertTrue(all(x['completed_ids'] == [] for x in inputs[:72]))

    def test_screen_report_uses_even_median_nearest_rank_and_excludes_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response)
            rows = [json.loads(p.read_bytes()) for p in sorted((root/'results').glob('*.json'))]
            evidence = root/'screen.png'
            evidence.write_bytes(b'offline screen fixture')
            screens = [dict(run_id=r['run_id'], request_id=r['request_id'], observed_upper_seconds=n+1,
                            method='first screenshot containing result', sample_interval_seconds=.5,
                            display_observed=True, evidence_path='screen.png',
                            evidence_sha256=qa.digest(evidence.read_bytes()))
                       for n, r in enumerate(rows[:10])]
            summary = launch.report(root, observations=screens)
            self.assertEqual(summary['timings']['first_action']['median'], 5.5)
            self.assertEqual(summary['timings']['first_action']['p90'], 9)
            self.assertTrue(summary['timings']['first_action']['sla_passed'])
            self.assertEqual(summary['timings']['smaller']['samples'], 0)
            self.assertIsNone(summary['server_timings']['first_action']['sla_passed'])
            self.assertEqual(summary['condition_timings']['fixed-ready']['first_action']['samples'], 3)
            self.assertIsNone(summary['condition_timings']['fixed-ready']['first_action']['p90'])
            self.assertIsNone(launch.report(root, observations=screens[:9])['timings']['first_action']['p90'])
            with self.assertRaises(ValueError):
                launch.report(root, observations=screens + screens[:1])
            with self.assertRaises(ValueError):
                launch.report(root, observations=[dict(screens[0], request_id='unrelated')])
            self.assertNotIn('필요한 정보', json.dumps(summary, ensure_ascii=False))
            (root.parent/'screen.png').write_bytes(evidence.read_bytes())
            (root/'outside.png').symlink_to(root.parent/'screen.png')
            for invalid in (dict(screens[0], evidence_path='missing.png'),
                            dict(screens[0], evidence_path='../screen.png'),
                            dict(screens[0], evidence_path='outside.png'),
                            dict(screens[0], evidence_sha256='a'*64)):
                with self.assertRaises(ValueError):
                    launch.report(root, observations=[invalid])
            evidence.write_bytes(b'changed after observation')
            with self.assertRaises(ValueError):
                launch.report(root, observations=screens)

    def test_auth_timeout_and_ownership_loss_reap_descendants_before_unlock(self):
        for ownership in (False, True):
            with self.subTest(ownership=ownership), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                fake = Path(directory)/'claude'
                pid_file = Path(directory)/'descendant.pid'
                fake.write_text('#!' + sys.executable + '\n' +
                    'import subprocess,time\n' +
                    'child=subprocess.Popen(["sleep","30"])\n' +
                    f'open({str(pid_file)!r},"w").write(str(child.pid))\n' +
                    'time.sleep(30)\n')
                fake.chmod(0o700)
                lock = Path(directory)/'model.lock'
                if ownership:
                    threading.Timer(.3, lambda: lock.unlink()).start()
                    summary = launch.run(root, claude=str(fake), lock_path=lock)
                    self.assertEqual(summary['stop_reason'], 'ownership_lost')
                    self.assertEqual(summary['roles']['started'], 0)
                else:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        launch.subscription_account(str(fake), threading.Event(), timeout=.3)
                pid = int(pid_file.read_text())
                for _ in range(30):
                    state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True).stdout.strip()
                    if not state or state.startswith(b'Z'):
                        break
                    time.sleep(.05)
                self.assertTrue(not state or state.startswith(b'Z'), state)

    def test_monthly_budget_and_elapsed_deadline_stop_before_more_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'launch'
            launch.freeze(root, owner='minjunkim-dev',
                ends_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(), delete_method='delete directory',
                monthly_spent_micro_usd=9_960_001)
            roles = []
            summary = launch.run(root, invoke=lambda *args: roles.append(args))
            self.assertEqual(summary['stop_reason'], 'monthly_budget_limit')
            self.assertEqual(roles, [])
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            now = [0]

            def invoke(role, *args):
                now[0] += 59
                result = self.response(role, *args)
                if role == 'generate' and not args[2]['unknown']:
                    result['output']['status'] = 'action'
                return result

            summary = launch.run(root, invoke=invoke, clock=lambda: now[0])
            self.assertEqual(summary['stop_reason'], 'time_limit')
            self.assertEqual(summary['requests']['started'], 46)

    def test_paid_calls_are_denied_and_preflight_is_only_an_offline_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            with self.assertRaises(ValueError):
                launch.run(root, mode='paid', invoke=self.response)
            self.assertFalse((root/'run-started.json').exists())
            missing = launch.paid_preflight('preparation', {})
            self.assertFalse(missing['ready'])
            ready = launch.paid_preflight('before_separate_server', dict.fromkeys(launch.PAID_CONDITIONS, True))
            self.assertTrue(ready['ready'])
            self.assertFalse(ready['transport_enabled'])

    def test_ownership_loss_cancels_and_reaps_active_child_without_next_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            fake = Path(directory)/'claude'
            fake.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n')
            fake.chmod(0o700)
            lock = Path(directory)/'model.lock'

            def invoke(role, prompt, schema, data, deadline, cancel):
                threading.Timer(.15, lambda: lock.unlink()).start()
                return qa.call(str(fake), prompt, schema, data, deadline, cancel, output_mode='text-json')

            summary = launch.run(root, invoke=invoke, lock_path=lock)
            self.assertEqual(summary['stop_reason'], 'ownership_lost')
            self.assertEqual(summary['roles']['started'], 1)
            row = json.loads(next((root/'results').glob('*.json')).read_bytes())
            self.assertTrue(row['calls'][0]['process_reaped'])
            self.assertFalse(row['calls'][0]['process_group_alive'])

    def test_concurrent_ownership_is_exclusive_across_distinct_frozen_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            second = Path(directory)/'second'
            launch.freeze(second, owner='minjunkim-dev',
                          ends_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
                          delete_method='delete private directory')
            lock = Path(directory)/'model.lock'
            attempts = []

            def invoke(role, *args):
                if not attempts:
                    with self.assertRaises(ValueError):
                        launch.run(second, invoke=self.response, lock_path=lock)
                    attempts.append(True)
                return self.response(role, *args)

            self.assertTrue(launch.run(root, invoke=invoke, lock_path=lock)['automatic_passed'])
            self.assertFalse((second/'run-started.json').exists())

    def test_interruption_during_role_preserves_started_request_and_conservative_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)

            def crash(*args):
                raise RuntimeError('DO-NOT-SAVE private provider error')

            summary = launch.run(root, invoke=crash)
            self.assertEqual(summary['requests']['started'], 1)
            self.assertEqual(summary['roles']['started'], 1)
            self.assertEqual(summary['roles']['failed'], 1)
            self.assertEqual(summary['costs']['conservative_roles'], 1)
            self.assertNotIn('DO-NOT-SAVE', json.dumps(summary))

    def test_report_rejects_state_callback_as_display_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            summary = launch.run(root, invoke=self.response)
            row = json.loads(next((root/'results').glob('*.json')).read_bytes())
            with self.assertRaises(ValueError):
                launch.report(root, observations=[dict(run_id=summary['run_id'], request_id=row['request_id'],
                    observed_upper_seconds=.1, sample_interval_seconds=0, method='state callback')])

    def test_cli_reuses_subscription_transport_without_extra_model_calls_or_raw_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            fake = Path(directory)/'claude'
            fake.write_text('#!' + sys.executable + '\n' + '''import json,sys
if sys.argv[1:] == ['auth','status']:
 print(json.dumps({'loggedIn':True,'authMethod':'claude.ai','apiProvider':'firstParty'}))
 sys.exit()
assert sys.argv[sys.argv.index('--model')+1] == 'claude-haiku-5-5'
assert sys.argv[sys.argv.index('--effort')+1] == 'xhigh'
assert sys.argv[sys.argv.index('--tools')+1] == ''
assert '--json-schema' not in sys.argv
data=json.load(sys.stdin)
if 'candidate' in data:
 out={'verdict':'accept','criteria':[1,2,3,4,5],'evidence':'private quote; fits'}
else:
 out={'status':'need_info','action':'private synthetic question','completion_condition':'answer unknown',
      'estimated_minutes':1,'reason':'private synthetic reason'}
print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))
print(json.dumps({'type':'result','subtype':'success','is_error':False,'modelUsage':{'claude-haiku-5-5':{}},
                  'usage':{'input_tokens':100,'output_tokens':30},'result':json.dumps(out)}))
''')
            fake.chmod(0o700)
            command = [sys.executable, str(qa.REPO/'scripts/launch_evaluation.py'), 'run', str(root), '--claude', str(fake)]
            result = subprocess.run(command, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary['roles']['model_messages'], 66)
            self.assertEqual(summary['role_usage']['generate']['input_tokens']['known_total'], 3300)
            self.assertEqual(summary['role_usage']['generate']['thinking_tokens']['unknown_calls'], 33)
            self.assertNotIn('private synthetic', result.stdout.decode())
            self.assertEqual(summary['costs']['conservative_roles'], 66)
            again = subprocess.run(command, capture_output=True, timeout=5)
            self.assertNotEqual(again.returncode, 0)

    def test_partial_report_preserves_missing_records_and_refuses_active_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response)
            (root/'summary.json').unlink()
            (root/'run-ended.json').unlink()
            with self.assertRaises(ValueError):
                launch.report(root)
            claim = json.loads((root/'run-started.json').read_bytes())
            claim['controller_birth'] = 'different process identity'
            (root/'run-started.json').write_bytes(qa.encoded(claim))
            result = next((root/'results').glob('*.json'))
            result.write_text('{truncated')
            summary = launch.report(root)
            self.assertFalse(summary['automatic_passed'])
            self.assertEqual(summary['requests']['unrecorded'], 1)
            self.assertEqual(summary['roles']['unrecorded'], 2)
            self.assertEqual(summary['stop_reason'], 'interrupted')
            self.assertEqual(summary['costs']['conservative_roles'], 66)

    def test_expected_rejection_is_separate_from_quality_failure_and_fast_failure_not_normal(self):
        for expected in (True, False):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root, manifest = self.freeze(directory)
                # Reference decision is frozen before any call; never change it after observing output.
                if expected:
                    for flow in manifest['flows']:
                        flow['expected']['verdicts'] = ['reject']
                    (root/'manifest.json').write_bytes(qa.encoded(manifest))
                    (root/'integrity.json').write_bytes(qa.encoded({'manifest_sha256': qa.digest((root/'manifest.json').read_bytes())}))

                def invoke(role, *args):
                    result = self.response(role, *args)
                    if role == 'check':
                        result['output']['verdict'] = 'reject'
                    return result

                summary = launch.run(root, invoke=invoke)
                self.assertEqual(summary['requests']['started'], 33 if expected else 1)
                self.assertEqual(summary['reference_mismatches'], 0 if expected else 1)
                self.assertEqual(summary['timings']['first_action']['samples'], 0)
                self.assertEqual(summary['terminations'], {'expected_reject': 33} if expected else {})

    def test_cancelled_request_timing_is_not_reported_as_normal_or_generic_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)

            def invoke(role, *args):
                result = self.response(role, *args)
                result.pop('output')
                result['error'] = 'cancelled'
                return result

            summary = launch.run(root, invoke=invoke)
            self.assertEqual(summary['outcomes'], {'cancelled': 1})
            self.assertEqual(len(summary['outcome_seconds']['cancelled']), 1)
            self.assertEqual(summary['outcome_seconds']['failed'], [])
            self.assertEqual(summary['timings']['first_action']['samples'], 0)

    def test_minimum_terminates_without_retry_and_malformed_generation_never_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)

            def minimum(role, *args):
                result = self.response(role, *args)
                if role == 'generate' and not args[2]['unknown']:
                    result['output']['status'] = 'minimum'
                return result

            summary = launch.run(root, invoke=minimum)
            self.assertEqual(summary['terminations'], {'minimum': 30, 'need_info': 3})
            self.assertEqual(summary['roles']['started'], 66)
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)

            def malformed(role, *args):
                result = self.response(role, *args)
                result['output']['estimated_minutes'] = 'private invalid value'
                return result

            summary = launch.run(root, invoke=malformed)
            self.assertEqual(summary['stop_reason'], 'invalid_output')
            self.assertEqual(summary['roles']['started'], 1)
            self.assertNotIn('private invalid value', json.dumps(summary))


if __name__ == '__main__':
    unittest.main()

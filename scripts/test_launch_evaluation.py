"""Offline regression at the frozen launch evaluator's execution/report boundary."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
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
        root = Path(directory).resolve() / "launch"
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
            original_read = Path.read_bytes
            def bounded_read(path):
                if path.resolve() == evidence.resolve():
                    raise AssertionError('screen evidence must be streamed')
                return original_read(path)
            with patch.object(Path, 'read_bytes', bounded_read):
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
            os.mkfifo(root/'pipe')
            for invalid in (dict(screens[0], evidence_path='missing.png'),
                            dict(screens[0], evidence_path='../screen.png'),
                            dict(screens[0], evidence_path='outside.png'),
                            dict(screens[0], evidence_path='pipe'),
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
                    def lose_after_start():
                        deadline = time.monotonic() + 5
                        while not pid_file.exists() and time.monotonic() < deadline:
                            time.sleep(.01)
                        lock.unlink()
                    threading.Thread(target=lose_after_start).start()
                    summary = launch.run(root, claude=str(fake), lock_path=lock)
                    self.assertEqual(summary['stop_reason'], 'ownership_lost')
                    self.assertEqual(summary['roles']['started'], 0)
                else:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        launch.subscription_account(str(fake), threading.Event(), timeout=2)
                pid = int(pid_file.read_text())
                for _ in range(30):
                    state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True).stdout.strip()
                    if not state or state.startswith(b'Z'):
                        break
                    time.sleep(.05)
                self.assertTrue(not state or state.startswith(b'Z'), state)

    def test_screen_open_rejects_concurrent_symlink_fifo_and_parent_replacement(self):
        for replacement in ('symlink', 'fifo', 'parent'):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                summary = launch.run(root, invoke=self.response)
                row = next(r for p in sorted((root/'results').glob('*.json'))
                           if (r := json.loads(p.read_bytes()))['request_kind'] == 'first_action')
                (root/'screens').mkdir()
                evidence = root/'screens/screen.png'
                evidence.write_bytes(b'offline evidence')
                outside = root.parent/'outside'
                outside.mkdir()
                (outside/'screen.png').write_bytes(evidence.read_bytes())
                observation = dict(run_id=summary['run_id'], request_id=row['request_id'],
                    observed_upper_seconds=1, sample_interval_seconds=.1, method='screen fixture',
                    display_observed=True, evidence_path='screens/screen.png',
                    evidence_sha256=qa.digest(evidence.read_bytes()))
                self.assertEqual(launch.report(root, observations=[observation])['timings']['first_action']['samples'], 1)
                original_open = os.open
                def replace_before_open(path, flags, *args, **kwargs):
                    if path == ('screens' if replacement == 'parent' else 'screen.png'):
                        if replacement == 'parent':
                            (root/'screens').rename(root/'original-screens')
                            (root/'screens').symlink_to(outside, target_is_directory=True)
                        else:
                            evidence.unlink()
                            if replacement == 'symlink':
                                evidence.symlink_to(outside/'screen.png')
                            else:
                                os.mkfifo(evidence)
                    return original_open(path, flags, *args, **kwargs)
                with patch.object(os, 'open', replace_before_open), self.assertRaises(ValueError):
                    launch.report(root, observations=[observation])

    def test_screen_open_rejects_bundle_root_symlink_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            summary = launch.run(root, invoke=self.response)
            row = next(r for p in sorted((root/'results').glob('*.json'))
                       if (r := json.loads(p.read_bytes()))['request_kind'] == 'first_action')
            (root/'screen.png').write_bytes(b'offline evidence')
            outside = root.parent/'outside'
            outside.mkdir()
            (outside/'screen.png').write_bytes((root/'screen.png').read_bytes())
            observation = dict(run_id=summary['run_id'], request_id=row['request_id'],
                observed_upper_seconds=1, sample_interval_seconds=.1, method='screen fixture',
                display_observed=True, evidence_path='screen.png',
                evidence_sha256=qa.digest((root/'screen.png').read_bytes()))
            original_resolve, original_open = Path.resolve, os.open
            replaced = []
            def replace_root(path):
                if path == root and not replaced:
                    root.rename(root.parent/'original-bundle')
                    root.symlink_to(outside, target_is_directory=True)
                    replaced.append(True)
            def resolve(path, *args, **kwargs):
                replace_root(path)
                return original_resolve(path, *args, **kwargs)
            def opening(path, flags, *args, **kwargs):
                replace_root(root if path == root.name else path)
                return original_open(path, flags, *args, **kwargs)
            with patch.object(Path, 'resolve', resolve), patch.object(os, 'open', opening), self.assertRaises(ValueError):
                launch.report(root, observations=[observation])
            self.assertEqual(replaced, [True])

    def test_screen_open_rejects_writable_bundle_ancestor_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            base = root.parent
            parent = base/'work'
            parent.mkdir()
            root.rename(parent/'launch')
            root = parent/'launch'
            summary = launch.run(root, invoke=self.response)
            row = next(r for p in sorted((root/'results').glob('*.json'))
                       if (r := json.loads(p.read_bytes()))['request_kind'] == 'first_action')
            (root/'screen.png').write_bytes(b'offline evidence')
            outside = base/'outside'
            (outside/'launch').mkdir(parents=True)
            (outside/'launch/screen.png').write_bytes((root/'screen.png').read_bytes())
            observation = dict(run_id=summary['run_id'], request_id=row['request_id'],
                observed_upper_seconds=1, sample_interval_seconds=.1, method='screen fixture',
                display_observed=True, evidence_path='screen.png',
                evidence_sha256=qa.digest((root/'screen.png').read_bytes()))
            original_open = os.open
            def opening(path, flags, *args, **kwargs):
                if path == 'work':
                    parent.rename(base/'original-work')
                    parent.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, *args, **kwargs)
            with patch.object(os, 'open', opening), self.assertRaises(ValueError):
                launch.report(root, observations=[observation])

    def test_monthly_budget_and_elapsed_deadline_stop_before_more_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'launch'
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

    def test_partial_report_isolates_valid_json_with_invalid_record_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response)
            result = next((root/'results').glob('*.json'))
            original = json.loads(result.read_bytes())
            malformed = [None, [], 'text', dict(original, calls=None),
                         dict(original, calls=[None]), dict(original, seconds='unknown'),
                         dict(original, error=[]), dict(original, request_id=[]), dict(original, flow='unrelated'),
                         dict(original, calls=[dict(original['calls'][0], usage=None)]),
                         dict(original, calls=[dict(original['calls'][0], provider_messages='one')]),
                         dict(original, seconds=10**1000),
                         dict(original, calls=[dict(original['calls'][0], usage={'input_tokens': 10**1000})])]
            for value in malformed:
                with self.subTest(value=value):
                    result.write_bytes(qa.encoded(value))
                    summary = launch.report(root)
                    self.assertEqual(summary['unreadable_records'], [result.name])
                    self.assertEqual(summary['requests']['recorded'], 32)
                    self.assertEqual(summary['roles']['unrecorded'], 2)
                    self.assertFalse(summary['automatic_passed'])

    def test_partial_report_isolates_usage_aggregation_overflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response)
            results = sorted((root/'results').glob('*.json'))
            for index, result in enumerate(results):
                row = json.loads(result.read_bytes())
                row['seconds'] = 1e308
                if index < 2:
                    row['calls'][0]['usage']['input_tokens'] = 1e308
                result.write_bytes(qa.encoded(row))
            summary = launch.report(root)
            self.assertEqual(summary['unreadable_records'], [results[1].name])
            self.assertEqual(summary['requests']['recorded'], 32)
            self.assertEqual(summary['roles']['unrecorded'], 2)
            self.assertEqual(summary['server_timings']['first_action']['median'], 1e308)
            self.assertEqual(summary['role_usage']['generate']['input_tokens']['known_total'], 1e308)
            self.assertFalse(summary['automatic_passed'])
            qa.encoded(summary)

    def test_partial_report_rejects_fifo_and_symlink_result_files_without_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response)
            extra = root/'results'/'999.json'
            for kind in ('fifo', 'symlink'):
                with self.subTest(kind=kind):
                    if kind == 'fifo':
                        os.mkfifo(extra)
                    else:
                        extra.symlink_to(next((root/'results').glob('*.json')))
                    child = subprocess.run([sys.executable, '-c',
                        'import json,sys; import launch_evaluation as l; print(json.dumps(l.report(sys.argv[1])))',
                        str(root)], env=dict(os.environ, PYTHONPATH=str(Path(launch.__file__).parent)),
                        capture_output=True, text=True, timeout=2, check=True)
                    summary = json.loads(child.stdout)
                    self.assertEqual(summary['unreadable_records'], ['999.json'])
                    self.assertEqual(summary['requests']['recorded'], 33)
                    self.assertFalse(summary['automatic_passed'])
                    extra.unlink()

    def test_result_paths_reject_results_root_and_ancestor_replacement(self):
        for target in ('results', 'root', 'ancestor'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
                root, _ = self.freeze(directory)
                launch.run(root, invoke=self.response)
                first = sorted((root/'results').glob('*.json'))[0]
                victim = {'results': root/'results', 'root': root, 'ancestor': root.parent}[target]
                foreign = Path(outside).resolve()/'replacement'
                shutil.copytree(victim, foreign)
                original = victim.with_name(victim.name+'.original')
                real_open, replaced = os.open, []

                def replace(path, flags, *args, **kwargs):
                    if not replaced and os.fspath(path) in (str(first), victim.name):
                        victim.rename(original)
                        victim.symlink_to(foreign, target_is_directory=True)
                        replaced.append(True)
                    return real_open(path, flags, *args, **kwargs)

                try:
                    with patch.object(launch.os, 'open', side_effect=replace):
                        with self.assertRaises(ValueError):
                            launch.report(root)
                    self.assertTrue(replaced)
                finally:
                    if replaced:
                        victim.unlink()
                        original.rename(victim)

    def test_report_rejects_fifo_and_symlink_execution_metadata_without_waiting(self):
        for name in ('run-started.json', 'run-ended.json'):
            for kind in ('fifo', 'symlink'):
                with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                    root, _ = self.freeze(directory)
                    launch.run(root, invoke=self.response)
                    metadata = root/name
                    preserved = root/(name+'.original')
                    metadata.rename(preserved)
                    if kind == 'fifo':
                        os.mkfifo(metadata)
                    else:
                        metadata.symlink_to(preserved)
                    child = subprocess.run([sys.executable, '-c',
                        'import sys; import launch_evaluation as l; l.report(sys.argv[1])', str(root)],
                        env=dict(os.environ, PYTHONPATH=str(Path(launch.__file__).parent)),
                        capture_output=True, text=True, timeout=2)
                    self.assertNotEqual(child.returncode, 0)

    def test_partial_report_bounds_oversized_and_deep_json_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response)
            extra = root/'results'/'999.json'
            limit = 16 * 1024 * 1024
            with extra.open('wb') as source:
                source.truncate(limit+1)
            real_loads = json.loads

            def bounded_parse(data, *args, **kwargs):
                self.assertLessEqual(len(data), limit)
                return real_loads(data, *args, **kwargs)

            with patch.object(launch.json, 'loads', side_effect=bounded_parse):
                summary = launch.report(root)
            self.assertEqual(summary['unreadable_records'], ['999.json'])
            real_stat = os.fstat

            def stale_size(descriptor):
                observed = real_stat(descriptor)
                if observed.st_size > limit:
                    fields = list(observed)
                    fields[6] = 0
                    return os.stat_result(fields)
                return observed

            with patch.object(launch.os, 'fstat', side_effect=stale_size), patch.object(launch.json, 'loads', side_effect=bounded_parse):
                self.assertEqual(launch.report(root)['unreadable_records'], ['999.json'])
            extra.write_text('['*2000 + '0' + ']'*2000)
            summary = launch.report(root)
            self.assertEqual(summary['unreadable_records'], ['999.json'])
            self.assertEqual(summary['requests']['recorded'], 33)
            self.assertFalse(summary['automatic_passed'])

    def test_frozen_control_json_rejects_fifo_and_symlink_without_waiting(self):
        for name in ('manifest.json', 'integrity.json', 'regression/manifest.json'):
            for kind in ('fifo', 'symlink'):
                with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                    root, _ = self.freeze(directory)
                    control = root/name
                    preserved = control.with_name(control.name+'.original')
                    control.rename(preserved)
                    if kind == 'fifo':
                        os.mkfifo(control)
                    else:
                        control.symlink_to(preserved)
                    child = subprocess.run([sys.executable, '-c',
                        'import sys; import launch_evaluation as l; l.load(sys.argv[1])', str(root)],
                        env=dict(os.environ, PYTHONPATH=str(Path(launch.__file__).parent)),
                        capture_output=True, timeout=2)
                    self.assertNotEqual(child.returncode, 0)

    def test_cli_observations_and_preflight_json_reject_fifo_and_symlink(self):
        for command in ('report', 'paid-preflight'):
            for kind in ('fifo', 'symlink'):
                with self.subTest(command=command, kind=kind), tempfile.TemporaryDirectory() as directory:
                    root, _ = self.freeze(directory)
                    if command == 'report':
                        launch.run(root, invoke=self.response)
                    argument = root/'argument.json'
                    preserved = root/'argument.original'
                    preserved.write_text('[]' if command == 'report' else '{}')
                    if kind == 'fifo':
                        os.mkfifo(argument)
                    else:
                        argument.symlink_to(preserved)
                    args = ([str(root), '--observations', str(argument)] if command == 'report'
                            else ['--stage', 'preparation', '--conditions', str(argument)])
                    child = subprocess.run([sys.executable, str(Path(launch.__file__)), command, *args],
                                           capture_output=True, text=True, timeout=2)
                    self.assertEqual(child.returncode, 1)
                    self.assertEqual(json.loads(child.stdout), {'error': 'launch_evaluation_failed'})

    def test_ownership_fifo_cancels_before_another_role_without_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            script = '''import os,sys; import launch_evaluation as l
roles=[]
def invoke(role,prompt,schema,data,deadline,cancelled):
 roles.append(role)
 claim=root/'run-started.json'; claim.rename(root/'claim.original'); os.mkfifo(claim)
 assert cancelled.wait(1), 'ownership monitor did not cancel'
 return {}
from pathlib import Path
root=Path(sys.argv[1])
try: l.run(root,invoke=invoke)
except ValueError: pass
assert roles == ['generate'], roles
print('cancelled')
'''
            child = subprocess.run([sys.executable, '-c', script, str(root)],
                env=dict(os.environ, PYTHONPATH=str(Path(launch.__file__).parent)),
                capture_output=True, text=True, timeout=3)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.strip(), 'cancelled')

    def test_missing_dangling_or_cancelled_end_cannot_pass_complete_records(self):
        for state in ('missing', 'dangling', 'cancelled'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                launch.run(root, invoke=self.response)
                claim = json.loads((root/'run-started.json').read_bytes())
                claim['controller_birth'] = 'expired controller identity'
                (root/'run-started.json').write_bytes(qa.encoded(claim))
                end = root/'run-ended.json'
                if state == 'cancelled':
                    data = json.loads(end.read_bytes())
                    data['reason'] = 'cancelled'
                    end.write_bytes(qa.encoded(data))
                else:
                    end.unlink()
                    if state == 'dangling':
                        end.symlink_to(root/'absent.json')
                summary = launch.report(root)
                self.assertEqual(summary['requests']['recorded'], 33)
                self.assertFalse(summary['automatic_passed'])
                child = subprocess.run([sys.executable, str(Path(launch.__file__)), 'report', str(root)],
                                       capture_output=True, text=True, timeout=2)
                self.assertEqual(child.returncode, 1)
                self.assertFalse(json.loads(child.stdout)['automatic_passed'])

    def test_report_pins_bundle_when_parent_is_replaced_by_regular_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            original = launch.run(root, invoke=self.response)
            replacement = root.with_name('replacement')
            shutil.copytree(root, replacement)
            next((root/'results').glob('*.json')).unlink()
            end = json.loads((replacement/'run-ended.json').read_bytes())
            end['budget']['charged_micro_usd'] = 999999
            (replacement/'run-ended.json').write_bytes(qa.encoded(end))
            real_json, replaced = launch.private_json, []

            def replace(bundle, name):
                value = real_json(bundle, name)
                if name == 'run-started.json' and not replaced:
                    root.rename(root.with_name('original'))
                    replacement.rename(root)
                    replaced.append(True)
                return value

            with patch.object(launch, 'private_json', side_effect=replace):
                summary = launch.report(root)
            self.assertTrue(replaced)
            self.assertEqual(summary['requests']['recorded'], 32)
            self.assertEqual(summary['costs']['charged_micro_usd'], original['costs']['charged_micro_usd'])
            self.assertFalse(summary['automatic_passed'])

    def test_cli_rejects_wrong_top_level_json_types_with_safe_error(self):
        for target, value in [('end', []), ('observations', {}), ('conditions', [])]:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                launch.run(root, invoke=self.response)
                argument = root/'argument.json'
                argument.write_bytes(qa.encoded(value))
                if target == 'end':
                    (root/'run-ended.json').write_bytes(qa.encoded(value))
                    args = ['report', str(root)]
                elif target == 'observations':
                    args = ['report', str(root), '--observations', str(argument)]
                else:
                    args = ['paid-preflight', '--stage', 'preparation', '--conditions', str(argument)]
                child = subprocess.run([sys.executable, str(Path(launch.__file__)), *args],
                                       capture_output=True, text=True, timeout=2)
                self.assertEqual(child.returncode, 1)
                self.assertEqual(json.loads(child.stdout), {'error': 'launch_evaluation_failed'})
                self.assertNotIn('Traceback', child.stderr)

    def test_report_isolates_corrupt_decision_and_role_output_consistency(self):
        changes = [lambda row: row.update(verdict='corrupt'),
                   lambda row: row.pop('criteria'),
                   lambda row: row.update(criteria=[1]),
                   lambda row: row.update(status='action'),
                   lambda row: row.update(reference_matched=False),
                   lambda row: row['calls'][1]['output'].update(verdict='reject'),
                   lambda row: row['calls'][1]['output'].update(criteria=[1]),
                   lambda row: row.update(termination='corrupt'),
                   lambda row: row['calls'][0]['output'].update(goal_completed=True),
                   lambda row: row['calls'][0]['output'].update(current_action_completed=True),
                   lambda row: row['calls'][0]['output'].update(remaining_work=[]),
                   lambda row: row['calls'][0]['output'].update(preserved_completed_ids=['invented']),
                   lambda row: row['calls'][0].update(actual_models=['other-model']),
                   lambda row: row['calls'][0].update(provider_messages=2),
                   lambda row: row['calls'][1].update(provider_retries=1),
                   lambda row: row['calls'][1]['usage'].update(input_tokens=None),
                   lambda row: row['calls'][0].update(cli_pid=123, process_reaped=False)]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                launch.run(root, invoke=self.response)
                path = next((root/'results').glob('*.json'))
                row = json.loads(path.read_bytes())
                change(row)
                path.write_bytes(qa.encoded(row))
                result = launch.report(root)
                self.assertFalse(result['automatic_passed'])
                self.assertEqual(result['requests']['recorded'], 32)
                self.assertEqual(result['unreadable_records'], [path.name])

    def test_report_pins_subdirectories_and_files_before_reading_claim(self):
        for target in ('results', 'requests', 'calls', 'result', 'end'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                original = launch.run(root, invoke=self.response)
                replacement = root.with_name('replacement')
                shutil.copytree(root, replacement)
                changed = next((root/'results').glob('*.json'))
                row = json.loads(changed.read_bytes())
                row['verdict'] = 'corrupt'
                changed.write_bytes(qa.encoded(row))
                if target in ('requests', 'calls'):
                    next((root/target).glob('*.json')).unlink()
                real_json, replaced = launch.private_json, []
                def replace(bundle, name):
                    value = real_json(bundle, name)
                    if name == 'run-started.json' and not replaced:
                        if target == 'result':
                            changed.rename(changed.with_suffix('.original'))
                            (replacement/'results'/changed.name).rename(changed)
                        elif target == 'end':
                            (root/'run-ended.json').rename(root/'end.original')
                            end = json.loads((replacement/'run-ended.json').read_bytes())
                            end['budget']['charged_micro_usd'] = 999999
                            (replacement/'run-ended.json').write_bytes(qa.encoded(end))
                            (replacement/'run-ended.json').rename(root/'run-ended.json')
                        else:
                            (root/target).rename(root/(target+'-original'))
                            (replacement/target).rename(root/target)
                        replaced.append(True)
                    return value
                with patch.object(launch, 'private_json', side_effect=replace):
                    result = launch.report(root)
                self.assertEqual(result['requests']['recorded'], 32)
                self.assertEqual(result['unreadable_records'], [changed.name])
                self.assertEqual(result['requests']['started'], 32 if target == 'requests' else 33)
                self.assertEqual(result['roles']['started'], 65 if target == 'calls' else 66)
                self.assertEqual(result['costs'], original['costs'])
                self.assertFalse(result['automatic_passed'])

    def test_report_detects_result_leaf_replacement_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response)
            path = next((root/'results').glob('*.json'))
            original = path.read_bytes()
            corrupt = json.loads(original)
            corrupt['verdict'] = 'corrupt'
            path.write_bytes(qa.encoded(corrupt))
            real_source, replaced = launch.private_source, []
            def replace(bundle, name):
                if type(bundle) is int and str(name) == path.name and not replaced:
                    path.rename(path.with_suffix('.original'))
                    path.write_bytes(original)
                    replaced.append(True)
                return real_source(bundle, name)
            with patch.object(launch, 'private_source', side_effect=replace):
                result = launch.report(root)
            self.assertTrue(replaced)
            self.assertFalse(result['automatic_passed'])
            self.assertEqual(result['unreadable_records'], [path.name])
            self.assertEqual(result['requests']['recorded'], 32)

    def test_completed_budget_respects_initial_and_monthly_limits(self):
        for charged, spent, allowed in [(9_999_999, 0, False), (3_000_000, 7_000_001, False),
                                        (3_000_000, 7_000_000, True)]:
            with self.subTest(charged=charged, spent=spent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()/'launch'
                launch.freeze(root, owner='minjunkim-dev',
                    ends_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
                    delete_method='delete directory', monthly_spent_micro_usd=spent)
                launch.run(root, invoke=self.response)
                end = json.loads((root/'run-ended.json').read_bytes())
                end['budget']['charged_micro_usd'] = charged
                (root/'run-ended.json').write_bytes(qa.encoded(end))
                if allowed:
                    self.assertTrue(launch.report(root)['automatic_passed'])
                else:
                    with self.assertRaises(ValueError):
                        launch.report(root)

    def test_completed_report_rejects_sequential_time_above_90_minutes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            generated = [0]
            def invoke(role, *args):
                result = self.response(role, *args)
                if role == 'generate':
                    generated[0] += 1
                    if generated[0] <= 72:
                        result['output']['status'] = 'action'
                return result
            original = launch.run(root, invoke=invoke)
            self.assertEqual(original['requests']['recorded'], 81)
            for elapsed, allowed in [(5670, False), (5400, True)]:
                for n, path in enumerate(sorted((root/'results').glob('*.json'))):
                    row = json.loads(path.read_bytes())
                    row['seconds'] = 70 if elapsed == 5670 else 40 if n == 0 else 67
                    path.write_bytes(qa.encoded(row))
                self.assertEqual(launch.report(root)['automatic_passed'], allowed)

    def test_maximum_report_fits_256_file_descriptors(self):
        with tempfile.TemporaryDirectory() as directory:
            script = '''import json,resource,sys
from pathlib import Path
from test_launch_evaluation import LaunchEvaluationTests
import launch_evaluation as l
import oauth_quality as q
resource.setrlimit(resource.RLIMIT_NOFILE,(256,resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
root,_=LaunchEvaluationTests().freeze(sys.argv[1])
generated=[0]
def invoke(role,*args):
 result=LaunchEvaluationTests.response(role,*args)
 if role=='generate':
  generated[0]+=1
  if generated[0]<=72: result['output']['status']='action'
 return result
summary=l.run(root,invoke=invoke)
assert summary['requests']['recorded']==81, summary['requests']
(root/'screens').mkdir()
observations=[]
for n,path in enumerate(sorted((root/'results').glob('*.json'))):
 row=json.loads(path.read_bytes()); evidence=root/'screens'/f'{n}.png'
 evidence.write_bytes(b'offline screen fixture')
 observations.append(dict(run_id=row['run_id'],request_id=row['request_id'],
  observed_upper_seconds=1,sample_interval_seconds=.5,method='screen fixture',
  display_observed=True,evidence_path=str(evidence.relative_to(root)),
  evidence_sha256=q.digest(evidence.read_bytes())))
assert l.report(root,observations=observations)['automatic_passed']
print('maximum report passed')
'''
            child = subprocess.run([sys.executable, '-c', script, directory],
                env=dict(os.environ, PYTHONPATH=str(Path(launch.__file__).parent)),
                capture_output=True, text=True, timeout=5)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.strip(), 'maximum report passed')

    def test_screen_png_does_not_change_snapshot_json_counts(self):
        for folder in ('results', 'requests', 'calls'):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                original = launch.run(root, invoke=self.response)
                row = json.loads(next((root/'results').glob('*.json')).read_bytes())
                evidence = root/folder/'screen.png'
                evidence.write_bytes(b'offline screen fixture')
                observation = dict(run_id=row['run_id'], request_id=row['request_id'],
                    observed_upper_seconds=1, sample_interval_seconds=.5,
                    method='first screenshot containing result', display_observed=True,
                    evidence_path=str(evidence.relative_to(root)), evidence_sha256=qa.digest(evidence.read_bytes()))
                result = launch.report(root, observations=[observation])
                self.assertTrue(result['automatic_passed'])
                self.assertEqual(result['requests'], original['requests'])
                self.assertEqual(result['roles'], original['roles'])
                self.assertEqual(result['unreadable_records'], [])

    def test_report_rejects_corrupt_end_budget(self):
        changes = [lambda end: end.update(budget=[]),
                   lambda end: end.pop('budget'),
                   lambda end: end['budget'].update(charged_micro_usd='0'),
                   lambda end: end['budget'].update(conservative_roles=-1),
                   lambda end: end['budget'].pop('monthly_spent_micro_usd'),
                   lambda end: end['budget'].update(basis=None),
                   lambda end: end['budget'].update(actual_billing=0)]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root, _ = self.freeze(directory)
                launch.run(root, invoke=self.response)
                path = root/'run-ended.json'
                end = json.loads(path.read_bytes())
                change(end)
                path.write_bytes(qa.encoded(end))
                with self.assertRaises(ValueError):
                    launch.report(root)

    def test_cli_rejects_non_string_screen_method_with_safe_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            launch.run(root, invoke=self.response)
            row = json.loads(next((root/'results').glob('*.json')).read_bytes())
            evidence = root/'screen.png'
            evidence.write_bytes(b'offline screen fixture')
            observation = dict(run_id=row['run_id'], request_id=row['request_id'],
                               observed_upper_seconds=1, sample_interval_seconds=.5,
                               method=1, display_observed=True, evidence_path='screen.png',
                               evidence_sha256=qa.digest(evidence.read_bytes()))
            argument = root/'observations.json'
            argument.write_bytes(qa.encoded([observation]))
            child = subprocess.run([sys.executable, str(Path(launch.__file__)), 'report', str(root),
                                    '--observations', str(argument)],
                                   capture_output=True, text=True, timeout=2)
            self.assertEqual(child.returncode, 1)
            self.assertEqual(json.loads(child.stdout), {'error': 'launch_evaluation_failed'})
            self.assertNotIn('Traceback', child.stderr)

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

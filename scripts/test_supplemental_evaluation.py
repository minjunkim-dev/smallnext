"""Synthetic, offline mixed-plan checks at the existing execution/report seam."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import launch_evaluation as launch
import oauth_quality as qa
import test_launch_evaluation as legacy


class SupplementalEvaluationTests(unittest.TestCase):
    response = staticmethod(legacy.LaunchEvaluationTests.response)

    def setUp(self):
        legacy.isolate_private_root(self)

    def flows(self):
        data = launch.initial('합성 자료 표시 남기기', ['합성 자료: 표시 A'], ['표시 남기기'])
        candidate = legacy.LaunchEvaluationTests.response('generate', None, None, data, None, None)['output']
        return [dict(id='synthetic-check-1', kind='check', repeat=1, input=data,
                     candidate=candidate, max_smaller=0,
                     expected={'statuses': ['need_info'], 'verdicts': ['accept'], 'meaning': 'synthetic'}),
                dict(id='synthetic-generate-1', kind='generate_check', repeat=1,
                     input=deepcopy(data), max_smaller=0,
                     expected={'statuses': ['need_info'], 'verdicts': ['accept'], 'meaning': 'synthetic'})]

    def freeze(self, directory, flows=None):
        root = Path(directory).resolve() / 'mixed'
        launch.freeze(root, owner='synthetic-owner',
                      ends_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                      delete_method='delete temporary synthetic bundle',
                      plan_kind='supplemental', flows=self.flows() if flows is None else flows)
        return root

    def test_mixed_plan_checks_fixed_candidate_without_generation_and_binds_each_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.freeze(directory)
            manifest = launch.load(root)
            received = []

            def invoke(role, prompt, schema, data, deadline, cancelled):
                received.append((role, deepcopy(data)))
                return legacy.LaunchEvaluationTests.response(role, prompt, schema, data, deadline, cancelled)

            summary = launch.run(root, invoke=invoke)
            self.assertEqual(manifest['version'], 2)
            self.assertEqual(manifest['plan_kind'], 'supplemental')
            self.assertIn('6385071594', manifest['contract'])
            self.assertEqual([role for role, _ in received], ['check', 'generate', 'check'])
            self.assertEqual(received[0][1]['candidate'], manifest['flows'][0]['candidate'])
            self.assertEqual(received[2][1]['original_request'], received[1][1])
            generated = json.loads((root/'results/001.json').read_bytes())['calls'][0]['output']
            self.assertEqual(received[2][1]['candidate'], generated)
            self.assertEqual(summary['planned'], {'units': 2, 'generate': 1, 'check': 2, 'roles': 3})
            self.assertEqual(summary['roles']['started'], 3)
            self.assertEqual(summary['roles']['completed'], 3)
            self.assertEqual(summary['provider_observations'], {
                'provider_messages': 3, 'provider_retries': 0, 'additional_provider_requests': 0})
            self.assertEqual([unit['state'] for unit in summary['units']], ['completed', 'completed'])
            self.assertTrue(summary['automatic_passed'])
            self.assertEqual(launch.report(root), summary)
            self.assertNotIn('합성 자료', json.dumps(summary, ensure_ascii=False))

    def test_admission_allows_role_123_only_as_a_single_check(self):
        budget = launch.Budget({'limits': launch.SUPPLEMENTAL_LIMITS}, lambda: 0)
        for _ in range(48):
            self.assertIsNone(budget.admit())
            self.assertIsNone(budget.start_role('generate'))
            self.assertIsNone(budget.start_role('check'))
        for _ in range(26):
            self.assertIsNone(budget.admit(('check',)))
            self.assertIsNone(budget.start_role('check'))
        self.assertEqual(budget.calls, 122)
        self.assertEqual(budget.admit(), 'call_limit')
        self.assertIsNone(budget.admit(('check',)))
        self.assertIsNone(budget.start_role('check'))
        self.assertEqual(budget.start_role('check'), 'call_limit')
        self.assertEqual(budget.calls, 123)

    def test_full_allowance_runs_once_without_filling_a_smaller_plan(self):
        for generation_count, check_count in [(48, 27), (1, 1)]:
            with self.subTest(generation_count=generation_count), tempfile.TemporaryDirectory() as directory:
                check, generate = self.flows()
                flows = [dict(deepcopy(generate), id=f'generate-{i}') for i in range(generation_count)]
                flows += [dict(deepcopy(check), id=f'check-{i}') for i in range(check_count)]
                root = self.freeze(directory, flows)
                roles = []

                def invoke(role, *args):
                    roles.append(role)
                    return self.response(role, *args)

                summary = launch.run(root, invoke=invoke)
                self.assertEqual(roles, ['generate', 'check'] * generation_count + ['check'] * check_count)
                self.assertEqual(summary['roles']['started'], 123 if generation_count == 48 else 3)
                self.assertEqual(summary['stop_reason'], 'completed')

    def test_technical_failures_stop_all_roles_and_preserve_unexecuted_reasons(self):
        for failed_role in ('generate', 'check'):
            for fault in ('provider_failed', 'timed_out', 'cancelled', 'wrong_model',
                          'output_limit', 'invalid_output', 'usage_unknown', 'process_cleanup', 'unexpected_retry'):
                with self.subTest(role=failed_role, fault=fault), tempfile.TemporaryDirectory() as directory:
                    check, generate = self.flows()
                    root = self.freeze(directory, [generate, check])
                    received = []

                    def invoke(role, *args):
                        received.append(role)
                        result = self.response(role, *args)
                        if role == failed_role:
                            if fault == 'wrong_model':
                                result['actual_models'] = ['unrequested-model']
                            elif fault == 'invalid_output':
                                result['output'] = {}
                            elif fault == 'usage_unknown':
                                result['usage'] = {}
                            elif fault == 'process_cleanup':
                                result.update(cli_pid=1, process_reaped=False, process_group_alive=True)
                            elif fault == 'unexpected_retry':
                                result['provider_retries'] = 1
                            else:
                                result['error'] = fault
                        return result

                    summary = launch.run(root, invoke=invoke)
                    expected = ('model_or_call_count' if fault == 'wrong_model' else fault)
                    self.assertEqual(summary['stop_reason'], expected)
                    self.assertEqual(received, ['generate'] if failed_role == 'generate' else ['generate', 'check'])
                    self.assertFalse(summary['automatic_passed'])
                    self.assertEqual(summary['units'][1]['state'], 'not_executed')
                    self.assertEqual(summary['units'][1]['reason'], expected)
                    failed = summary['units'][0]['roles'][0 if failed_role == 'generate' else 1]
                    self.assertEqual(failed['reason'], expected)
                    self.assertEqual(summary['roles']['completed'], 0 if failed_role == 'generate' else 1)
                    if failed_role == 'generate':
                        self.assertEqual(summary['units'][0]['roles'][1]['state'], 'not_executed')
                        self.assertEqual(summary['role_counts']['check']['started'], 0)

    def test_cancel_and_ownership_loss_before_check_do_not_start_it(self):
        for fault in ('cancelled', 'ownership_lost'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = self.freeze(directory, list(reversed(self.flows())))
                cancel, roles = threading.Event(), []
                lock = Path(directory) / 'model.lock'

                def invoke(role, *args):
                    roles.append(role)
                    if fault == 'cancelled':
                        cancel.set()
                    else:
                        lock.unlink()
                    return self.response(role, *args)

                summary = launch.run(root, invoke=invoke, cancelled=cancel, lock_path=lock)
                self.assertEqual(summary['stop_reason'], fault)
                self.assertEqual(roles, ['generate'])
                self.assertEqual(summary['role_counts']['check']['started'], 0)

    def test_unit_deadlines_are_shared_and_stop_at_the_boundary(self):
        for kind in ('check', 'generate_check'):
            for offset in (-.001, 0, .001):
                with self.subTest(kind=kind, offset=offset), tempfile.TemporaryDirectory() as directory:
                    flow = self.flows()[0 if kind == 'check' else 1]
                    root = self.freeze(directory, [flow])
                    now, deadlines = [0.0], []
                    limit = 120 if kind == 'check' else 180

                    def invoke(role, *args):
                        deadlines.append(args[-2])
                        now[0] += 70 if role == 'generate' else limit + offset - (70 if kind == 'generate_check' else 0)
                        return self.response(role, *args)

                    summary = launch.run(root, invoke=invoke, clock=lambda: now[0])
                    self.assertEqual(deadlines, [limit] * (1 if kind == 'check' else 2))
                    self.assertEqual(summary['stop_reason'], 'completed' if offset < 0 else 'timed_out')
                    self.assertEqual(summary['automatic_passed'], offset < 0)
                    self.assertAlmostEqual(summary['elapsed_seconds'], limit + offset)

    def test_expiry_before_role_start_does_not_invoke_or_count_a_role(self):
        for gap in (180, 180.001, 5400):
            with self.subTest(gap=gap), tempfile.TemporaryDirectory() as directory:
                root = self.freeze(directory, [self.flows()[1]])
                now, roles = [0], []
                save = qa.save

                def slow_record(path, value):
                    save(path, value)
                    if path.parent.name == 'requests' and path.suffix == '.json':
                        now[0] = gap

                def invoke(role, *args):
                    roles.append(role)
                    return self.response(role, *args)

                with patch.object(qa, 'save', slow_record):
                    summary = launch.run(root, invoke=invoke, clock=lambda: now[0])
                self.assertEqual(roles, [])
                self.assertEqual(summary['roles']['started'], 0)
                self.assertEqual(summary['stop_reason'], 'time_limit' if gap >= 5400 else 'timed_out')
                self.assertEqual(summary['units'][0]['roles'][0]['state'], 'not_executed')

    def test_generation_cannot_start_a_checker_at_or_after_the_shared_deadline(self):
        for offset in (0, .001):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as directory:
                root = self.freeze(directory, [self.flows()[1]])
                roles, now = [], [0]

                def invoke(role, *args):
                    roles.append(role)
                    now[0] = 180 + offset
                    return self.response(role, *args)

                summary = launch.run(root, invoke=invoke, clock=lambda: now[0])
                self.assertEqual(roles, ['generate'])
                self.assertEqual(summary['stop_reason'], 'timed_out')
                self.assertEqual(summary['role_counts']['check']['started'], 0)

    def test_fixed_rejection_and_uncertainty_are_completed_checks(self):
        for verdict in ('reject', 'uncertain'):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as directory:
                check = self.flows()[0]
                check['expected']['verdicts'] = [verdict]
                root = self.freeze(directory, [check])

                def invoke(role, *args):
                    result = self.response(role, *args)
                    result['output']['verdict'] = verdict
                    return result

                summary = launch.run(root, invoke=invoke)
                self.assertTrue(summary['automatic_passed'])
                self.assertEqual(summary['role_counts']['generate']['started'], 0)
                self.assertEqual(summary['units'][0]['state'], 'completed')

    def test_plan_rejects_extra_generation_roles_and_invalid_units(self):
        check, generate = self.flows()
        invalid = [[dict(deepcopy(generate), id=f'generate-{i}') for i in range(49)],
                   [dict(deepcopy(generate), id=f'generate-{i}') for i in range(48)] +
                   [dict(deepcopy(check), id=f'check-{i}') for i in range(28)],
                   [check, check], [dict(check, id='../outside')], [dict(check, kind='other')],
                   [dict(check, repeat=4)], [dict(check, repeat=True)], [dict(check, max_smaller=1)],
                   [dict(check, candidate={})], [dict(generate, candidate=check['candidate'])],
                   [dict(check, input=dict(check['input'], available_minutes=-1))]]
        for flows in invalid:
            with self.subTest(size=len(flows), kind=flows[0]['kind']), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    self.freeze(directory, flows)

    def test_global_deadline_wins_over_a_new_request_and_over_its_checker(self):
        for offset in (-.001, 0, .001):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as directory:
                check, generate = self.flows()
                flows = [dict(deepcopy(check), id=f'check-{i}', repeat=i % 3 + 1) for i in range(44)]
                flows.append(generate)
                root = self.freeze(directory, flows)
                now, received = [0.0], []

                def invoke(role, *args):
                    received.append((role, args[-2]))
                    if role == 'generate':
                        now[0] += 100
                    elif len(received) <= 44:
                        now[0] += 119
                    else:
                        now[0] = 5400 + offset
                    return self.response(role, *args)

                summary = launch.run(root, invoke=invoke, clock=lambda: now[0])
                self.assertEqual(received[-2:], [('generate', 5400), ('check', 5400)])
                self.assertEqual(summary['stop_reason'], 'completed' if offset < 0 else 'time_limit')
                self.assertAlmostEqual(summary['elapsed_seconds'], 5400 + offset)

    def test_recording_and_repeat_changes_are_in_the_one_global_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            check = self.flows()[0]
            flows = [dict(deepcopy(check), id=f'check-{i}', repeat=i // 21 + 1) for i in range(61)]
            root = self.freeze(directory, flows)
            now, roles = [0], []
            save = qa.save

            def slow_record(path, value):
                save(path, value)
                if path.parent.name == 'results':
                    now[0] += 89

            def invoke(role, *args):
                roles.append(role)
                now[0] += 1
                return self.response(role, *args)

            with patch.object(qa, 'save', slow_record):
                summary = launch.run(root, invoke=invoke, clock=lambda: now[0])
            self.assertEqual(roles, ['check'] * 60)
            self.assertEqual(summary['stop_reason'], 'time_limit')
            self.assertEqual(summary['elapsed_seconds'], 5400)
            self.assertEqual(summary['units'][-1]['reason'], 'time_limit')
            self.assertFalse(summary['automatic_passed'])

    def test_active_call_is_cancelled_and_cleanup_time_is_retained(self):
        for kind in ('check', 'generate_check'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = self.freeze(directory, [self.flows()[0 if kind == 'check' else 1]])
                now, roles = [0], []

                def invoke(role, *args):
                    roles.append(role)
                    now[0] = args[-2]
                    self.assertTrue(args[-1].wait(2), 'deadline must cancel the active invocation')
                    now[0] += 7  # cancellation/reaping may safely overrun; it earns no more calls
                    return dict(self.response(role, *args), error='cancelled',
                                cli_pid=1, process_reaped=True, process_group_alive=False)

                summary = launch.run(root, invoke=invoke, clock=lambda: now[0])
                self.assertEqual(roles, ['check'] if kind == 'check' else ['generate'])
                self.assertEqual(summary['stop_reason'], 'timed_out')
                self.assertEqual(summary['elapsed_seconds'], 127 if kind == 'check' else 187)
                self.assertEqual(summary['roles']['completed'], 0)
                self.assertFalse(summary['automatic_passed'])

    def test_new_plan_validation_and_live_cli_entry_are_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.freeze(directory)
            original = launch.load(root)
            changes = [dict(version=3), dict(contract='different-contract'), dict(plan_kind='other'),
                       dict(limits=dict(original['limits'], calls=124)), dict(check_seconds=121),
                       dict(pipeline_seconds=181), dict(flows=original['flows'] * 38)]
            for change in changes:
                with self.subTest(change=list(change)):
                    raw = qa.encoded(dict(original, **change))
                    (root/'manifest.json').write_bytes(raw)
                    (root/'integrity.json').write_bytes(qa.encoded({'manifest_sha256': qa.digest(raw)}))
                    with self.assertRaises(ValueError):
                        launch.load(root)
            raw = qa.encoded(original)
            (root/'manifest.json').write_bytes(raw)
            (root/'integrity.json').write_bytes(qa.encoded({'manifest_sha256': qa.digest(raw)}))
            fake = Path(directory) / 'must-not-run'
            fake.write_text('#!/bin/sh\nexit 99\n')
            fake.chmod(0o700)
            for command in ([sys.executable, launch.__file__, 'run', str(root), '--claude', str(fake)],
                            [sys.executable, launch.__file__, 'freeze', str(Path(directory) / 'blocked'),
                             '--plan-kind', 'supplemental', '--owner', 'synthetic',
                             '--ends-at', original['retention']['evaluation_ends_at'], '--delete-method', 'delete']):
                child = subprocess.run(command, capture_output=True, text=True, timeout=5)
                self.assertEqual(child.returncode, 1)
                self.assertEqual(json.loads(child.stdout), {'error': 'launch_evaluation_failed'})
            self.assertFalse((root/'run-started.json').exists())
            self.assertFalse((Path(directory)/'blocked').exists())
            launch.run(root, invoke=self.response)
            with self.assertRaises(FileExistsError):
                launch.run(root, invoke=self.response)
            with self.assertRaises(FileExistsError):
                self.freeze(directory)


if __name__ == '__main__':
    unittest.main()

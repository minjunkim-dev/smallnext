"""Offline execution/report checks for #287; mock output is not AI quality evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import launch_evaluation as launch
import oauth_quality as qa
import test_launch_evaluation as legacy


class SupplementalFixedPlanTests(unittest.TestCase):
    def setUp(self):
        legacy.isolate_private_root(self)

    def freeze(self, directory):
        root = Path(directory).resolve() / 'fixed'
        launch.freeze(root, owner='synthetic-owner',
                      ends_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                      delete_method='delete temporary synthetic bundle',
                      plan_kind='supplemental-fixed', flows=launch.supplemental.fixed_flows())
        return root, launch.load(root)

    @staticmethod
    def response(role, prompt, schema, data, deadline, cancelled):
        result = legacy.LaunchEvaluationTests.response(role, prompt, schema, data, deadline, cancelled)
        if role == 'generate':
            fresh = any('참여자 세 명의 일정을 조율' in fact for fact in data['available'])
            result['output'].update(
                status='action' if fresh else 'insufficient_info',
                action='사용자 진술로 표시하여 일정 조율 경험 한 가지를 메모하기' if fresh else '',
                completion_condition='사용자 진술 표시와 경험 한 가지가 메모에 있다' if fresh else '',
                estimated_minutes=1 if fresh else 0,
                reduction='세부 경력 작성에서 제공된 경험 하나의 선택 표시로 범위를 줄인다' if fresh else '')
        else:
            shared = json.loads((qa.REPO / 'contracts/fixtures/insufficient-info.json').read_bytes())
            case = next((case for case in shared['checker_cases'] if case['input'] == data['original_request']), None)
            if case:
                result['output'] = deepcopy(case['check'])
        return result

    def test_fixed_plan_runs_three_independent_repeats_and_reports_all_75_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            received = []

            def invoke(role, prompt, schema, data, deadline, cancelled):
                received.append((role, deepcopy(data)))
                return self.response(role, prompt, schema, data, deadline, cancelled)

            summary = launch.run(root, invoke=invoke, clock=lambda: 0)
            self.assertEqual(manifest['version'], 3)
            self.assertEqual(summary['planned'], {'units': 75, 'generate': 48, 'check': 75, 'roles': 123})
            self.assertEqual([role for role, _ in received], (['check'] * 9 + ['generate', 'check'] * 16) * 3)
            self.assertEqual([data['request_kind'] for role, data in received if role == 'generate'],
                             [kind for kind in ('first_action', 'next_action', 'smaller', 'replacement')
                              for _ in range(4)] * 3)
            self.assertEqual(summary['scheduled_flows'], 51)
            self.assertEqual(summary['completed_flows'], 51)
            self.assertTrue(summary['automatic_passed'])
            self.assertEqual(summary['human_review'], 'not_performed')
            self.assertIsNone(summary['quality_passed'])
            self.assertEqual(len(summary['units']), 75)
            self.assertEqual(summary['roles']['started'], 123)
            self.assertEqual(len({unit['unit_id'] for unit in summary['units']}), 75)
            self.assertEqual([flow['case_id'] for flow in manifest['flows'][:9]], [
                'no-source-or-answer', 'useful-source-check', 'real-unanswered-question',
                'conflicting-sources', 'source-omission-is-not-absence', 'memory-without-details',
                'known-unknown-rewrite', 'unsupported-fill-in', 'specific-user-statement'])
            self.assertEqual([flow['branch'] for flow in manifest['flows'][9:17]],
                             ['new-facts', 'still-unknown'] * 4)
            self.assertEqual(launch.report(root), summary)
            generated = [data for role, data in received if role == 'generate']
            for offset in (0, 16, 32):
                for index in range(0, 16, 2):
                    before, after = generated[offset + index:offset + index + 2]
                    for key in ('goal', 'remaining_work', 'completed_ids', 'previous_proposals', 'request_kind'):
                        self.assertEqual(before[key], after[key])
                    self.assertEqual(after['available'][:-1], before['available'])
                self.assertEqual(generated[offset:offset + 16], generated[:16])

    def test_semantic_failure_stops_only_the_affected_flow_at_either_stage(self):
        for kind in ('first_action', 'next_action', 'smaller', 'replacement'):
            for branch in ('new-facts', 'still-unknown'):
                for stage in ('initial', 'explicit_rerequest'):
                    with self.subTest(kind=kind, branch=branch, stage=stage), tempfile.TemporaryDirectory() as directory:
                        root, manifest = self.freeze(directory)
                        target = next(flow for flow in manifest['flows'] if flow.get('branch') == branch
                                      and flow['input']['request_kind'] == kind)
                        generated_flows = [flow for flow in manifest['flows'] if flow['kind'] == 'generate_check']
                        target_number = generated_flows.index(target) * 2 + (1 if stage == 'initial' else 2)
                        generated, failed = [0], [False]

                        def invoke(role, prompt, schema, data, deadline, cancelled):
                            result = self.response(role, prompt, schema, data, deadline, cancelled)
                            if role == 'generate':
                                generated[0] += 1
                            if role == 'check' and generated[0] == target_number and not failed[0]:
                                result['output']['verdict'] = 'reject'
                                failed[0] = True
                            return result

                        summary = launch.run(root, invoke=invoke, clock=lambda: 0)
                        self.assertEqual(summary['stop_reason'], 'completed')
                        self.assertEqual(summary['reference_mismatches'], 1)
                        units = [unit for unit in summary['units'] if unit['id'] == target['id']]
                        self.assertEqual(units[0]['state'], 'failed' if stage == 'initial' else 'completed')
                        self.assertEqual(units[1]['state'], 'not_executed' if stage == 'initial' else 'failed')
                        self.assertEqual(units[1]['reason'], 'initial_semantic_failure' if stage == 'initial' else 'unexpected_quality')
                        self.assertEqual(summary['roles']['started'], 121 if stage == 'initial' else 123)
                        self.assertEqual(summary['units'][-1]['state'], 'completed')
                        self.assertFalse(summary['automatic_passed'])
                        self.assertEqual(launch.report(root), summary)

    def test_fixed_expected_reject_and_uncertain_are_distinct_from_checker_misjudgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            failed = [False]

            def invoke(role, prompt, schema, data, deadline, cancelled):
                result = self.response(role, prompt, schema, data, deadline, cancelled)
                if role == 'check' and result['output']['verdict'] == 'reject' and not failed[0]:
                    result['output']['verdict'] = 'accept'
                    result['output']['criteria'] = [1, 2, 3, 4, 5]
                    failed[0] = True
                return result

            summary = launch.run(root, invoke=invoke, clock=lambda: 0)
            self.assertEqual(summary['units'][1]['state'], 'failed')
            self.assertEqual(summary['units'][3]['state'], 'completed')
            self.assertEqual(summary['reference_mismatches'], 1)
            self.assertEqual(summary['roles']['started'], 123)
            self.assertFalse(summary['automatic_passed'])

    def test_technical_failure_in_any_kind_branch_stage_and_role_stops_the_whole_plan(self):
        for kind in ('first_action', 'next_action', 'smaller', 'replacement'):
            for branch in ('new-facts', 'still-unknown'):
                for step in (0, 1):
                    for failed_role in ('generate', 'check'):
                        with self.subTest(kind=kind, branch=branch, step=step, role=failed_role), tempfile.TemporaryDirectory() as directory:
                            root, manifest = self.freeze(directory)
                            flows = [flow for flow in manifest['flows'] if flow['kind'] == 'generate_check']
                            index = next(i for i, flow in enumerate(flows) if flow['branch'] == branch
                                         and flow['input']['request_kind'] == kind)
                            target_number = index * 2 + step + 1
                            generated, calls = [0], []

                            def invoke(role, prompt, schema, data, deadline, cancelled):
                                calls.append(role)
                                if role == 'generate':
                                    generated[0] += 1
                                result = self.response(role, prompt, schema, data, deadline, cancelled)
                                if role == failed_role and generated[0] == target_number:
                                    result['error'] = 'provider_failed'
                                return result

                            summary = launch.run(root, invoke=invoke, clock=lambda: 0)
                            expected_calls = 9 + (target_number - 1) * 2 + (1 if failed_role == 'generate' else 2)
                            self.assertEqual(len(calls), expected_calls)
                            self.assertEqual(summary['roles']['started'], expected_calls)
                            self.assertEqual(summary['stop_reason'], 'provider_failed')
                            self.assertTrue(all(unit['state'] == 'not_executed' and unit['reason'] == 'provider_failed'
                                                for unit in summary['units'][9 + target_number:]))
                            self.assertFalse(summary['automatic_passed'])
                            self.assertEqual(launch.report(root), summary)

    def test_missing_changed_or_downgraded_fixed_plan_is_rejected_before_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root, original = self.freeze(directory)
            changes = [dict(version=2, plan_kind='supplemental'), dict(plan_id='unsupported'),
                       dict(flows=original['flows'][:-1]), dict(flows=list(reversed(original['flows']))),
                       dict(prompts={}), dict(schemas={}), dict(model='other'), dict(effort='low'),
                       dict(output_mode='structured'), dict(measurement={}), dict(plan_sha256='0' * 64)]
            changes.append(dict(retention=dict(original['retention'], owner='')))
            changes.append(dict(output_token_limit=16384))
            manifests = [dict(deepcopy(original), **change) for change in changes]
            for key in ('plan_id', 'plan_sha256', 'contract', 'retention', 'sources'):
                changed = deepcopy(original)
                changed.pop(key)
                manifests.append(changed)
            for index, manifest in enumerate(manifests):
                with self.subTest(variant=index):
                    # Resealing the transport checksum cannot substitute for the fixed contract.
                    if 'plan_sha256' in manifest and manifest['plan_sha256'] != '0' * 64:
                        manifest['plan_sha256'] = launch.supplemental.binding(manifest)
                    raw = qa.encoded(manifest)
                    (root / 'manifest.json').write_bytes(raw)
                    (root / 'integrity.json').write_bytes(qa.encoded({'manifest_sha256': qa.digest(raw)}))
                    with self.assertRaises((ValueError, KeyError)):
                        launch.run(root, invoke=self.response)
                    self.assertFalse((root / 'run-started.json').exists())

    def test_fixed_plan_live_entry_points_remain_blocked_without_starting_a_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.freeze(directory)
            fake = Path(directory) / 'must-not-run'
            marker = Path(directory) / 'invoked'
            fake.write_text('#!/bin/sh\ntouch ' + str(marker) + '\nexit 99\n')
            fake.chmod(0o700)
            for command in ([sys.executable, launch.__file__, 'run', str(root), '--claude', str(fake)],
                            [sys.executable, launch.__file__, 'freeze', str(Path(directory) / 'blocked'),
                             '--plan-kind', 'supplemental-fixed', '--owner', 'synthetic',
                             '--ends-at', manifest['retention']['evaluation_ends_at'], '--delete-method', 'delete']):
                child = subprocess.run(command, capture_output=True, text=True, timeout=5)
                self.assertEqual(child.returncode, 1)
                self.assertEqual(json.loads(child.stdout), {'error': 'launch_evaluation_failed'})
            self.assertFalse(marker.exists())
            self.assertFalse((root / 'run-started.json').exists())
            self.assertFalse((Path(directory) / 'blocked').exists())

    def test_accepted_but_unexpected_rerequest_status_is_a_flow_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            generated = [0]

            def invoke(role, prompt, schema, data, deadline, cancelled):
                result = self.response(role, prompt, schema, data, deadline, cancelled)
                if role == 'generate':
                    generated[0] += 1
                    if generated[0] == 2:
                        result['output'].update(status='insufficient_info', action='', completion_condition='',
                                                estimated_minutes=0, reduction='')
                return result

            summary = launch.run(root, invoke=invoke, clock=lambda: 0)
            self.assertEqual(summary['units'][10]['verdict'], 'accept')
            self.assertEqual(summary['units'][10]['status'], 'insufficient_info')
            self.assertEqual(summary['units'][10]['reason'], 'unexpected_quality')
            self.assertEqual(summary['reference_mismatches'], 1)
            self.assertEqual(summary['units'][-1]['state'], 'completed')

    def test_rerequest_has_its_own_shared_180_seconds_within_the_one_global_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.freeze(directory)
            now, generated, deadlines = [0], [0], []

            def invoke(role, prompt, schema, data, deadline, cancelled):
                if role == 'generate':
                    generated[0] += 1
                if generated[0] in (1, 2):
                    deadlines.append(deadline)
                    now[0] += 70 if role == 'generate' else 100
                elif not generated[0]:
                    now[0] += 1
                return self.response(role, prompt, schema, data, deadline, cancelled)

            summary = launch.run(root, invoke=invoke, clock=lambda: now[0])
            self.assertEqual(deadlines, [189, 189, 359, 359])
            self.assertEqual(summary['elapsed_seconds'], 349)
            self.assertTrue(summary['automatic_passed'])


if __name__ == '__main__':
    unittest.main()

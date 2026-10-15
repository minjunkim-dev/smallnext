"""Offline checks at the human-review preparation report boundary."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import human_review
import launch_evaluation as launch
import oauth_quality as qa


class HumanReviewTests(unittest.TestCase):
    def bundle(self, directory):
        root = Path(directory).resolve() / 'launch'
        with patch.object(launch, 'private_root', lambda: root.parent):
            launch.freeze(root, owner='minjunkim-dev',
                          ends_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                          delete_method='delete this synthetic test bundle')

        def invoke(role, prompt, schema, data, deadline, cancelled):
            if role == 'generate':
                output = dict(status='action', action='PRIVATE_SENTINEL',
                              completion_condition='PRIVATE_SENTINEL', estimated_minutes=2,
                              reason='PRIVATE_SENTINEL', remaining_work=data['remaining_work'],
                              preserved_completed_ids=data['completed_ids'],
                              goal_completed=False, current_action_completed=False)
            else:
                smaller = data['original_request']['request_kind'] == 'smaller'
                output = dict(verdict='reject' if smaller else 'accept',
                              criteria=[1, 4] if smaller else [1, 2, 3, 4, 5],
                              evidence='PRIVATE_SENTINEL', reason='PRIVATE_SENTINEL')
            return dict(output=output, payload_sha256=qa.digest(qa.encoded(data)),
                        actual_models=[qa.MODEL], seconds=1,
                        provider_messages=1, provider_retries=0,
                        additional_provider_requests=0,
                        usage={'input_tokens': 1, 'output_tokens': 1})

        launch.run(root, invoke=invoke)
        rows = [json.loads((root / 'results' / f'{i:03d}.json').read_text()) for i in range(2)]
        receipt = dict(run_version='synthetic-test',
                       launch_manifest_sha256=qa.digest((root / 'manifest.json').read_bytes()),
                       launch_rows=[dict(run_id=r['run_id'], request_id=r['request_id'],
                                         flow=r['flow'], step=r['step'], request_kind=r['request_kind'],
                                         **{k: r[k] for k in ('status', 'verdict', 'criteria', 'error',
                                                             'reference_matched', 'structure_valid',
                                                             'termination') if k in r},
                                         roles=[dict(role=c['role'], payload_sha256=c['payload_sha256'],
                                                     output_sha256=qa.digest(qa.encoded(c['output'])))
                                                for c in r['calls']]) for r in rows])
        return root, receipt

    def test_ready_report_links_same_inputs_without_judging_or_copying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root, receipt = self.bundle(directory)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = human_review.prepare(root, receipt=receipt)
            self.assertTrue(result['ready'])
            self.assertEqual(result['human_review'], 'not_performed')
            self.assertIsNone(result['quality_passed'])
            self.assertEqual((result['model_calls'], result['paid_calls']), (0, 0))
            self.assertEqual(result['case_id'], 'fixed-ready-1')
            self.assertEqual(len(result['request_ids']), 2)
            self.assertGreaterEqual(len(result['links']), 7)
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
            self.assertEqual(before, {p.relative_to(root): p.read_bytes()
                                     for p in root.rglob('*') if p.is_file()})

    def test_missing_and_mismatched_sources_block_preparation_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root, receipt = self.bundle(directory)
            source = root / 'results/001.json'
            original = source.read_bytes()
            source.unlink()
            missing = human_review.prepare(root, receipt=receipt)
            self.assertFalse(missing['ready'])
            self.assertIn('results/001.json', missing['missing'])
            self.assertEqual(missing['mismatched'], [])
            source.write_bytes(original)
            row = json.loads(original)
            row['calls'][0]['output']['action'] = 'changed private source'
            source.write_bytes(qa.encoded(row))
            changed = human_review.prepare(root, receipt=receipt)
            self.assertFalse(changed['ready'])
            self.assertEqual(changed['missing'], [])
            self.assertIn('1:generate:output', changed['mismatched'])
            source.write_bytes(original)
            (root / 'manifest.json').write_bytes((root / 'manifest.json').read_bytes() + b' ')
            self.assertIn('manifest.json', human_review.prepare(root, receipt=receipt)['mismatched'])

    def test_swapped_request_binding_and_role_receipt_block_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root, receipt = self.bundle(directory)
            ident = receipt['launch_rows'][1]['request_id']
            path = root / f'calls/{ident}-check.receipt'
            value = json.loads(path.read_bytes())
            value['request_id'] = receipt['launch_rows'][0]['request_id']
            path.write_bytes(qa.encoded(value))
            result = human_review.prepare(root, receipt=receipt)
            self.assertFalse(result['ready'])
            self.assertTrue(result['mismatched'])

    def test_changed_decision_with_rehashed_receipt_blocks_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root, receipt = self.bundle(directory)
            ident = receipt['launch_rows'][1]['request_id']
            source = root / 'results/001.json'
            completion = root / f'requests/{ident}.receipt'
            original = json.loads(source.read_bytes())
            recorded = json.loads(completion.read_bytes())
            for key, value in [('status', 'minimum'), ('verdict', 'accept'),
                               ('criteria', [1, 2, 3, 4, 5]), ('error', None),
                               ('reference_matched', True), ('structure_valid', False),
                               ('termination', 'planned_limit'), ('criteria', [True, 4]),
                               ('reference_matched', 0), ('structure_valid', 1)]:
                with self.subTest(key=key, value=value):
                    changed = original | {key: value}
                    source.write_bytes(qa.encoded(changed))
                    completion.write_bytes(qa.encoded(recorded | {
                        'record_sha256': qa.digest(qa.encoded(changed))}))
                    result = human_review.prepare(root, receipt=receipt)
                    self.assertFalse(result['ready'])
                    self.assertIn(f'results/001.json:{key}', result['mismatched'])
                    self.assertNotIn('results/001.json:completion hash', result['mismatched'])
                    self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_unavailable_bundle_and_unsafe_files_never_leak_private_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root, receipt = self.bundle(directory)
            absent = human_review.prepare(root / 'absent', receipt=receipt)
            self.assertEqual(absent['missing'], ['bundle'])
            self.assertFalse(absent['ready'])
            source = root / 'results/001.json'
            secret = root / 'secret.json'
            secret.write_text('{"secret":"PRIVATE_SENTINEL"}')
            source.unlink()
            for kind in ('symlink', 'fifo', 'malformed'):
                with self.subTest(kind=kind):
                    if kind == 'symlink':
                        source.symlink_to(secret)
                    elif kind == 'fifo':
                        os.mkfifo(source)
                    else:
                        source.write_text('PRIVATE_SENTINEL')
                    result = human_review.prepare(root, receipt=receipt)
                    self.assertFalse(result['ready'])
                    self.assertIn('results/001.json', result['unreadable'])
                    self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
                    source.unlink()

    def test_cli_reports_blocked_missing_without_running_a_model(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('sys.argv', ['human_review.py', str(Path(directory).resolve() / 'absent')]), \
                    patch('builtins.print') as output, \
                    patch('subprocess.Popen', side_effect=AssertionError('no subprocess permitted')):
                self.assertEqual(human_review.main(), 1)
            result = json.loads(output.call_args.args[0])
            self.assertEqual(result['missing'], ['bundle'])
            self.assertEqual((result['model_calls'], result['paid_calls']), (0, 0))


if __name__ == '__main__':
    unittest.main()

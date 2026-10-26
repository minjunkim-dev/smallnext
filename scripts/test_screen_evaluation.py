"""Synthetic observer/clock and fake transport only; never invoke a model or simulator."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import oauth_quality as qa
import screen_evaluation as screen
from test_oauth_output_limit import fake_command


class ScreenEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.enterContext(patch.object(screen.launch, 'private_root', return_value=self.root))
        self.bundle = self.root / 'screen-once'
        self.now = 100.0
        self.clock = lambda: self.now
        self.parent = threading.Event()
        self.cli = Path(sys.executable).resolve()
        screen.freeze(self.bundle, owner='minjunkim-dev',
                      ends_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
                      delete_method='remove only this new bundle', claude=self.cli, observer=__file__)
        self.seen = []
        self.cache = []

    def result(self, output):
        return {'output': output, 'actual_models': [qa.MODEL], 'provider_messages': 1,
                'process_reaped': True, 'process_group_alive': False,
                'usage': {'input_tokens': 100, 'output_tokens': 40}}

    def calls(self, index, slot, change=None):
        data = deepcopy(slot['input'])
        candidate = dict(status='action', action='제공된 작업 중 한 개를 처리하기',
            completion_condition='한 개를 처리했다.', estimated_minutes=1, reason='제공된 자료를 사용한다.',
            remaining_work=data['remaining_work'], preserved_completed_ids=[], goal_completed=False,
            current_action_completed=False, facts=[], reduction='작업 수를 한 개로 줄인다.')
        generated = self.result(candidate)
        checked = self.result({'verdict': 'accept', 'criteria': [1, 2, 3, 4, 5],
                               'evidence': '제공된 한 작업', 'reason': '제공된 한 작업'})
        if change:
            change(generated, checked)
        screen.role_call(self.bundle, data, lambda *_: generated, self.parent, clock=self.clock)
        return screen.role_call(self.bundle, {'original_request': data, 'candidate': candidate},
                                lambda *_: checked, self.parent, clock=self.clock)

    def observe(self, index, slot, budget, change=None):
        # A previous sample is durable before another synthetic UI request may start.
        self.assertEqual(len(list((self.bundle / 'samples').glob('*.png'))), index)
        self.seen.append(slot['id'])
        self.calls(index, slot)
        self.now += 2
        ident, png = str(uuid.uuid4()), b'\x89PNG\r\n\x1a\nsynthetic-photo'
        app = {'runID': ident, 'requestKind': slot['input']['request_kind'], 'outcome': 'action',
               'server': {'run_id': ident, 'generate_ms': 1000, 'check_ms': 1000, 'total_ms': 2000}}
        self.cache = (self.cache + [app])[-16:]
        observation = {'run_id': ident, 'request_kind': slot['input']['request_kind'],
                       'expected_outcome': 'action', 'termination': 'observed', 'missing_screenshot': False,
                       'observed_upper_seconds': 2, 'budget_seconds': 180,
                       'evidence_sha256': qa.digest(png), 'max_sample_interval_seconds': .8}
        if change:
            change(observation, app)
        return observation, app, png

    def test_full_twenty_archives_beyond_cache_and_requires_pixel_review(self):
        screen.run(self.bundle, self.observe, approved_once=True, clock=self.clock)
        self.assertEqual(len(self.seen), 20)
        self.assertEqual(len(self.cache), 16)
        self.assertEqual(len(list((self.bundle / 'calls').glob('*-started.json'))), 40)
        self.assertEqual(len(screen.report(self.bundle)['pending_pixel_reviews']), 20)
        for index in range(20):
            row = json.loads((self.bundle / 'samples' / f'{index:02d}.json').read_bytes())
            qa.save(self.bundle / 'samples' / f'{index:02d}-review.json',
                    {'screenshot_sha256': row['screenshot_sha256'], 'basis': 'agent_pixel_review',
                     'visible_normal_result': True})
        report = screen.report(self.bundle)
        self.assertEqual(report['timings']['first_action']['samples'], 10)
        self.assertEqual(report['timings']['smaller']['p90'], 2)
        with self.assertRaises(FileExistsError):
            screen.run(self.bundle, self.observe, approved_once=True, clock=self.clock)
        self.assertEqual(len(self.seen), 20)

    def test_default_hold_and_single_publication(self):
        with self.assertRaisesRegex(ValueError, 'approval'):
            screen.run(self.bundle, self.observe)
        self.assertFalse((self.bundle / 'run-started.json').exists())
        with self.assertRaises(FileExistsError):
            screen.freeze(self.bundle, owner='owner', ends_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                          delete_method='private', claude=self.cli, observer=__file__)

    def test_missing_photo_uuid_mismatch_and_late_capture_stop_without_padding(self):
        def bad(index, slot, budget):
            return self.observe(index, slot, budget, lambda observation, _: observation.update(evidence_sha256='0' * 64))
        with self.assertRaises(ValueError):
            screen.run(self.bundle, bad, approved_once=True, clock=self.clock)
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(screen.report(self.bundle)['started_roles'], 2)
        self.assertEqual(screen.report(self.bundle)['timings']['first_action']['samples'], 0)

    def test_reject_preserves_usage_and_never_starts_next_request(self):
        def reject(index, slot, budget):
            self.calls(index, slot, lambda _, check: check['output'].update(verdict='reject'))
            raise ValueError('stopped')
        with self.assertRaises(ValueError):
            screen.run(self.bundle, reject, approved_once=True, clock=self.clock)
        record = json.loads((self.bundle / 'calls/00-check.json').read_bytes())
        self.assertEqual(record['error'], 'unexpected_quality')
        self.assertEqual(record['usage']['output_tokens'], 40)
        self.assertEqual(len(list((self.bundle / 'armed').glob('*.json'))), 1)

    def test_duplicate_generate_and_wrong_input_never_call_transport(self):
        def duplicate(index, slot, budget):
            self.calls(index, slot)
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                screen.role_call(self.bundle, slot['input'], lambda *_: self.fail('unexpected call'), self.parent, clock=self.clock)
            raise ValueError('stopped')
        with self.assertRaises(ValueError):
            screen.run(self.bundle, duplicate, approved_once=True, clock=self.clock)
        self.assertEqual(len(list((self.bundle / 'calls').glob('*-started.json'))), 2)

    def test_shared_lock_blocks_before_claim_and_absolute_cutoff_stops(self):
        with (self.root / 'launch-model.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'owns the model'):
                screen.run(self.bundle, self.observe, approved_once=True)
        self.assertFalse((self.bundle / 'run-started.json').exists())
        def elapsed(index, slot, budget):
            self.now += 3601
            return self.observe(index, slot, budget)
        with self.assertRaises(ValueError):
            screen.run(self.bundle, elapsed, approved_once=True, clock=self.clock)
        self.assertEqual(len(list((self.bundle / 'calls').glob('*-started.json'))), 0)

    def test_wrong_input_and_unverified_generation_never_start_checker(self):
        def wrong(index, slot, budget):
            data = dict(slot['input'], goal='not in the approved plan')
            screen.role_call(self.bundle, data, lambda *_: self.fail('unapproved call'), self.parent, clock=self.clock)
        with self.assertRaises(ValueError):
            screen.run(self.bundle, wrong, approved_once=True, clock=self.clock)
        self.assertFalse(list((self.bundle / 'calls').glob('*-started.json')))

    def test_cli_bridge_uses_session_gate_and_preserves_full_output(self):
        fake = self.root / 'fake-claude'
        fake.write_text('#!' + sys.executable + '''
import json,sys
data=json.load(sys.stdin)
output=({'verdict':'accept','criteria':[1,2,3,4,5],'evidence':'provided task'} if 'candidate' in data else
 {'status':'action','action':'책 한 권을 아래 칸으로 옮기기','completion_condition':'책 한 권이 아래 칸에 있다.',
  'estimated_minutes':1,'reason':'제공된 책과 칸을 사용한다.','facts':[],'reduction':''})
print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}),flush=True)
print(json.dumps({'type':'result','subtype':'success','is_error':False,'modelUsage':{'claude-haiku-5-5':{}},
 'usage':{'input_tokens':100,'output_tokens':40},'result':json.dumps(output)}),flush=True)
''')
        fake.chmod(0o700)
        bundle = self.root / 'bridge-once'
        screen.freeze(bundle, owner='owner', ends_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                      delete_method='private', claude=fake, observer=__file__)
        def bridge_observer(index, slot, budget):
            data = deepcopy(slot['input'])
            for role in ('generate', 'check'):
                command = fake_command(qa.REPO / 'scripts/oauth_bridge.py', '--claude', fake,
                    '--output-mode', 'text-json', '--screen-session', bundle, '--records', bundle / 'bridge',
                    '--output-schema', qa.REPO / f'services/api/src/suggestion/{role}.json',
                    '-c', 'model_instructions_file=' + json.dumps(str(qa.REPO / f'services/api/src/suggestion/{role}.md')))
                completed = subprocess.run(command, input=json.dumps(data), text=True, capture_output=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stdout)
                output = json.loads(json.loads(completed.stdout.splitlines()[0])['item']['text'])
                if role == 'generate':
                    data = {'original_request': slot['input'], 'candidate': output}
            # Deliberately stop after the two fake subprocesses. No real UI or padding.
            raise ValueError('end synthetic process-boundary test')
        with self.assertRaises(ValueError):
            screen.run(bundle, bridge_observer, approved_once=True)
        self.assertEqual(json.loads((bundle / 'calls/00-check.json').read_bytes())['output']['verdict'], 'accept')
        self.assertEqual(json.loads((bundle / 'calls/00-generate.json').read_bytes())['usage']['output_tokens'], 40)


if __name__ == '__main__':
    unittest.main()

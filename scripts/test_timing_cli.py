"""Offline checks at the synthetic CLI boundary. Never wait 35 seconds here."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'services/api/tests/fixtures/timing-cli/codex'


class TimingCLITests(unittest.TestCase):
    def invoke(self, kind, *, check=False, delayed=False, notice=False, followup=False, answered=False):
        payload = json.loads((ROOT / 'services/api/examples/development-ai-input.json').read_bytes())
        payload['request_kind'] = kind
        if notice: payload['goal'] = '정보 부족 안내 검증'
        if followup: payload['goal'] = f'후속 질문 검증 {kind}'
        if answered: payload['available'].append('행동 요청에서 이미 답한 질문: 기록이 있나요? / 답: 모르고 자료도 없어요.')
        if check:
            payload = {'original_request': payload, 'candidate': {}}
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / 'codex'
            shutil.copyfile(CLI, cli)
            if delayed:
                cli.with_name('delay-first-action').touch()
            schema = Path(directory) / 'schema.json'
            schema.write_text(json.dumps({'properties': {'verdict': {}} if check else {}}))
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), \
                    patch('sys.argv', [str(cli), '--output-schema', str(schema)]), \
                    patch('sys.stdin', io.StringIO(json.dumps(payload))), \
                    patch('time.sleep') as sleep, contextlib.redirect_stdout(output):
                runpy.run_path(str(cli), run_name='__main__')
            if delayed:
                recorded = json.loads(cli.with_name('calls.jsonl').read_text())
                self.assertEqual(recorded['configured_wait_seconds'], sleep.call_args.args[0])
                self.assertEqual(recorded['request_kind'], kind)
                self.assertEqual(recorded['actual_model_calls'], 0)
                self.assertEqual(recorded['paid_calls'], 0)
            else:
                self.assertFalse(cli.with_name('calls.jsonl').exists())
            value = json.loads(json.loads(output.getvalue().splitlines()[0])['item']['text'])
            return sleep.call_args_list, value

    def test_only_first_action_generation_waits_35_seconds(self):
        waits, value = self.invoke('first_action', delayed=True)
        self.assertEqual([call.args[0] for call in waits], [35])
        self.assertEqual(value['status'], 'action')
        self.assertEqual(value['action'], '펜 다섯 개 정리하기')
        waits, value = self.invoke('first_action', check=True, delayed=True)
        self.assertEqual([call.args[0] for call in waits], [.15])
        self.assertEqual(value['verdict'], 'accept')
        self.assertEqual(value['criteria'], [1, 2, 3, 4, 5])

    def test_default_and_goal_preparation_keep_the_existing_wait(self):
        for kind, delayed in [('first_action', False), ('goal_preparation', True)]:
            waits, _ = self.invoke(kind, delayed=delayed)
            self.assertEqual([call.args[0] for call in waits], [.15])

    def test_first_notice_has_no_fabricated_action_or_completion(self):
        _, value = self.invoke('first_action', notice=True)
        self.assertEqual(value['status'], 'insufficient_info')
        self.assertEqual(value['action'], '')
        self.assertEqual(value['completion_condition'], '')
        self.assertEqual(value['estimated_minutes'], 0)
        self.assertEqual(value['reduction'], '')
        self.assertFalse(value['goal_completed'])
        self.assertFalse(value['current_action_completed'])

    def test_each_action_question_stops_with_notice_after_an_unknown_answer(self):
        for kind in ['first_action', 'smaller', 'next_action', 'replacement']:
            _, value = self.invoke(kind, followup=True)
            self.assertEqual(value['status'], 'need_info')
            self.assertEqual(value['action'], '직접 확인할 수 있는 기록이 있나요?')
            _, value = self.invoke(kind, followup=True, answered=True)
            self.assertEqual(value['status'], 'insufficient_info')
            self.assertEqual(value['action'], '')
            self.assertEqual(value['completion_condition'], '')

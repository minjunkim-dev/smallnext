"""Offline checks at the subscription CLI process boundary; never call Claude."""
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import oauth_quality as qa


def permit_fake_cli(test):
    """Only fake-process tests replace the intentionally blocked production readiness."""
    test.enterContext(patch.object(qa, 'output_readiness', return_value={
        'ready': True, 'provider_application': 'fake_cli_only'}))


def fake_command(script, *args):
    # The replacement lives in the test subprocess, never in a production flag or environment variable.
    return [sys.executable, '-c',
            "import runpy,sys; from pathlib import Path; from unittest.mock import patch; "
            "sys.path.insert(0,str(Path(sys.argv[1]).parent)); import oauth_quality as qa; "
            "sys.argv=sys.argv[1:]; "
            "patch.object(qa,'output_readiness',return_value={'ready':True,'provider_application':'fake_cli_only'}).start(); "
            "qa.main() if Path(sys.argv[0]).stem=='oauth_quality' else runpy.run_path(sys.argv[0],run_name='__main__')",
            str(script), *map(str, args)]


class OutputLimitTests(unittest.TestCase):
    def invoke(self, events, *, linger=False):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'claude'
            setup = "import subprocess,time\nchild=subprocess.Popen([sys.executable,'-c'," + repr(
                "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(30)") + \
                "],stdout=subprocess.PIPE)\nchild.stdout.readline()\n" if linger else ''
            fake.write_text('#!' + sys.executable + '\nimport sys\nsys.stdin.read()\n' + setup +
                            '\n'.join('print(' + repr(json.dumps(e)) + ', flush=True)' for e in events) +
                            ('\ntime.sleep(30)\n' if linger else '\n'))
            fake.chmod(0o700)
            schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                      'required': ['ok'], 'additionalProperties': False}
            with patch.object(qa, 'output_readiness', return_value={'ready': True}):
                return qa.call(str(fake), 'prompt', schema, {}, qa.monotonic()+2,
                               threading.Event(), output_mode='text-json')

    def test_usage_and_stream_failures_are_distinct_without_retry(self):
        start = {'type': 'stream_event', 'event': {'type': 'message_start'}}
        success = {'type': 'result', 'subtype': 'success', 'is_error': False,
                   'modelUsage': {qa.MODEL: {}}, 'usage': {'output_tokens': 8192}, 'result': '{"ok":true}'}
        for events, error in (
                ([start, dict(success, usage={})], 'unverified_output_usage'),
                ([start, dict(success, usage=None)], 'unverified_output_usage'),
                ([start, dict(success, usage={'output_tokens': True})], 'unverified_output_usage'),
                ([start, {'type': 'stream_event', 'event': {'type': 'message_delta',
                  'usage': {'output_tokens': 'PRIVATE'}}}], 'unverified_output_usage'),
                ([start, dict(success, usage={'output_tokens': 8193})], 'output_tokens_exceeded'),
                ([start, dict(success, usage={'output_tokens': 10**400})], 'output_tokens_exceeded'),
                ([start, {'type': 'stream_event', 'event': {'type': 'message_delta',
                  'usage': {'output_tokens': 8193}}}], 'output_tokens_exceeded'),
                ([start, {'type': 'stream_event', 'event': {'type': 'message_delta',
                  'usage': {'output_tokens': 7}}}, success], 'output_usage_mismatch'),
                ([start, dict(success, modelUsage={qa.MODEL: {'outputTokens': 8193}})], 'output_tokens_exceeded'),
                ([start, {'type': 'stream_event', 'event': {'type': 'message_delta',
                  'delta': {'stop_reason': 'max_tokens'}}}], 'max_tokens'),
                ([start, start, success], 'additional_provider_request'),
                ([start, {'type': 'system', 'subtype': 'api_retry'}, success], 'provider_retry'),
                ([start, dict(success, modelUsage={'other': {}})], 'wrong_model'),
                ([start, dict(success, result='{"ok":')], 'invalid_output')):
            with self.subTest(error=error, events=events):
                record = self.invoke(events)
                self.assertEqual(record.get('error'), error, record)
                self.assertNotIn('output', record)
                self.assertTrue(record['process_reaped'])
                self.assertFalse(record['process_group_alive'])
                self.assertNotIn('PRIVATE', json.dumps(record))
        record = self.invoke([start, dict(success, usage={})])
        self.assertIsNone(record['usage']['output_tokens'])

    def test_cap_error_reaps_live_group_and_preserves_cleanup_failure(self):
        events = [{'type': 'stream_event', 'event': {'type': 'message_start'}},
                  {'type': 'stream_event', 'event': {'type': 'message_delta',
                   'delta': {'stop_reason': 'max_tokens'}}}]
        record = self.invoke(events, linger=True)
        self.assertEqual(record['error'], 'max_tokens', record)
        self.assertTrue(record['process_reaped'])
        self.assertFalse(record['process_group_alive'])
        killpg = os.killpg

        def failed_term(pid, sig):
            if sig == qa.signal.SIGTERM:
                raise OSError('PRIVATE')
            return killpg(pid, sig)

        with patch.object(qa.os, 'killpg', side_effect=failed_term):
            record = self.invoke(events)
        self.assertEqual(record['error'], 'process_cleanup')
        self.assertEqual(record['primary_error'], 'max_tokens')
        self.assertEqual(record['cleanup_error'], 'signal_failed')
        self.assertNotIn('PRIVATE', json.dumps(record))

    def test_cancel_and_timeout_reap_child_that_never_reads_large_stdin(self):
        for reason in ('cancelled', 'timed_out'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory)/'pid'
                fake = Path(directory)/'claude'
                fake.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\n' +
                                f'Path({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n')
                fake.chmod(0o700)
                cancel = threading.Event()
                results = []
                deadline = qa.monotonic() + (.2 if reason == 'timed_out' else 5)
                with patch.object(qa, 'output_readiness', return_value={'ready': True}):
                    worker = threading.Thread(target=lambda: results.append(qa.call(str(fake), '', {},
                        {'input': 'x'*180000}, deadline, cancel)))
                    worker.start()
                    timer = threading.Timer(.2, cancel.set)
                    if reason == 'cancelled':
                        timer.start()
                    worker.join(2)
                    blocked = worker.is_alive()
                    if blocked:
                        # Keep a failing regression from leaving its fake child or writer behind.
                        if marker.exists():
                            os.killpg(int(marker.read_text()), qa.signal.SIGKILL)
                        worker.join(2)
                    if reason == 'cancelled':
                        timer.join()
                self.assertFalse(blocked, 'stdin write prevented cancellation/deadline handling')
                self.assertEqual(results[0]['error'], reason, results)
                self.assertTrue(results[0]['process_reaped'])
                self.assertFalse(results[0]['process_group_alive'])

    def test_unverified_missing_or_changed_support_blocks_child_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'support.json'
            changed = Path(directory) / 'changed.json'
            changed.write_text('{"ready":true,"output_tokens":65536}')
            for source in (qa.REPO / 'docs/research/claude-output-limit-support.json', missing, changed):
                with self.subTest(source=source), patch.object(qa, 'OUTPUT_SUPPORT', source), \
                        patch.object(qa.subprocess, 'Popen') as spawn:
                    result = qa.call('must-not-start', '', {}, {}, qa.monotonic()+2, threading.Event())
                    self.assertEqual(result.get('error'), 'output_limit_unverified')
                    self.assertFalse(result['output_limit_support']['ready'])
                    self.assertTrue(result['output_limit_support']['reasons'])
                    self.assertNotIn('cli_pid', result)
                    spawn.assert_not_called()
            result = subprocess.run([sys.executable, str(qa.REPO/'scripts/oauth_quality.py'), 'readiness'],
                                    capture_output=True, text=True, timeout=2)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(result.stdout)['ready'])

    def test_each_role_gets_fixed_limit_and_subscription_isolation(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
                  "required": ["ok"], "additionalProperties": False}
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "claude"
            fake.write_text('#!' + sys.executable + '\n' + '''import json,os,sys
assert os.environ['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] == '8192'
assert not any(k.startswith(('ANTHROPIC_', 'CLAUDE_CODE_USE_', 'MCP_', 'MAX_THINKING_')) for k in os.environ)
assert 'CLAUDE_CODE_OAUTH_TOKEN' not in os.environ
assert sys.argv[sys.argv.index('--model')+1] == 'claude-haiku-5-5'
assert sys.argv[sys.argv.index('--effort')+1] == 'xhigh'
assert sys.argv[sys.argv.index('--tools')+1] == ''
assert json.loads(sys.argv[sys.argv.index('--settings')+1]) == {'forcedLoginMethod':'claudeai','disableAllHooks':True}
assert sys.argv[sys.argv.index('--mcp-config')+1] == '{"mcpServers":{}}'
assert '--strict-mcp-config' in sys.argv and '--no-session-persistence' in sys.argv
assert sys.argv[sys.argv.index('--setting-sources')+1] == ''
data=json.load(sys.stdin)
out={'verdict':'accept','criteria':[1,2,3,4,5],'evidence':'quote; fits'} if 'candidate' in data else {'ok':True}
print(json.dumps({'type':'stream_event','event':{'type':'message_start'}}))
print(json.dumps({'type':'result','subtype':'success','is_error':False,
 'modelUsage':{'claude-haiku-5-5':{}},'usage':{'output_tokens':8192},'structured_output':out,'result':json.dumps(out)}))
''')
            fake.chmod(0o700)
            for parent in (None, '65536', 'invalid'):
                env = dict(os.environ, ANTHROPIC_API_KEY='PRIVATE', CLAUDE_CODE_USE_BEDROCK='1',
                           CLAUDE_CODE_OAUTH_TOKEN='PRIVATE', MAX_THINKING_TOKENS='99999', MCP_SECRET='PRIVATE')
                env.pop('CLAUDE_CODE_MAX_OUTPUT_TOKENS', None)
                if parent is not None:
                    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = parent
                for role_data in ({}, {'original_request': {}, 'candidate': {}}):
                    with self.subTest(parent=parent, check=bool(role_data)), patch.dict(os.environ, env, clear=True), \
                            patch.object(qa, 'output_readiness', return_value={'ready': True}):
                        role_schema = json.loads((qa.REPO/'services/api/src/suggestion/check.json').read_bytes()) if role_data else schema
                        for mode in ('structured', 'text-json'):
                            result = qa.call(str(fake), 'prompt', role_schema, role_data,
                                             qa.monotonic()+2, threading.Event(), output_mode=mode)
                            expected = {'verdict':'accept','criteria':[1,2,3,4,5],
                                        'evidence':'quote; fits','reason':'quote; fits'} if role_data else {'ok':True}
                            self.assertEqual(result.get('output'), expected, result)
                            self.assertTrue(result['process_reaped'])
                            self.assertFalse(result['process_group_alive'])


if __name__ == '__main__':
    unittest.main()

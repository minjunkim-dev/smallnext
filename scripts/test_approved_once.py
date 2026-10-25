"""Explicit single-plan opt-in at fake CLI and frozen-run boundaries; no real calls."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import launch_evaluation as launch
import oauth_quality as qa
import test_launch_evaluation as legacy
import test_supplemental_fixed_plan as fixed


class ApprovedOnceTests(unittest.TestCase):
    def setUp(self):
        legacy.isolate_private_root(self)

    def freeze(self, directory, *, plan_kind='supplemental-once', approved_once=True):
        root = Path(directory).resolve()/'approved'
        launch.freeze(root, owner='synthetic-owner', ends_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
            delete_method='delete temporary synthetic bundle', plan_kind=plan_kind, approved_once=approved_once)
        return root

    def test_explicit_approval_reaches_fake_cli_without_bypassing_support_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory)/'claude'
            fake.write_text('#!'+sys.executable+'\nimport json,os,sys\nsys.stdin.read()\n'
                'assert os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]=="8192"\n'
                'print(json.dumps({"type":"stream_event","event":{"type":"message_start"}}),flush=True)\n'
                'print(json.dumps({"type":"result","subtype":"success","is_error":False,\n'
                '"modelUsage":{"'+qa.MODEL+'":{}},"usage":{"output_tokens":1},"result":"{\\"ok\\":true}"}),flush=True)\n')
            fake.chmod(0o700)
            schema=dict(type='object', properties=dict(ok=dict(type='boolean')), required=['ok'], additionalProperties=False)
            for approval in (False, 1, 'yes'):
                with self.subTest(approval=approval), patch.object(qa.subprocess, 'Popen') as spawn:
                    result=qa.call(str(fake),'prompt',schema,{},qa.monotonic()+2,threading.Event(),
                                   output_mode='text-json',approved_once=approval)
                    self.assertEqual(result['error'],'evaluation_not_authorized');spawn.assert_not_called()
            result=qa.call(str(fake),'prompt',schema,{},qa.monotonic()+2,threading.Event(),
                           output_mode='text-json',approved_once=True)
            self.assertEqual(result.get('output'),dict(ok=True),result)
            self.assertTrue(result['output_limit_support']['actual_execution_authorized'])
            self.assertTrue(result['process_reaped'])
            with patch.object(qa,'OUTPUT_SUPPORT',Path(directory)/'missing'), patch.object(qa.subprocess,'Popen') as spawn:
                result=qa.call(str(fake),'prompt',schema,{},qa.monotonic()+2,threading.Event(),approved_once=True)
                self.assertEqual(result['error'],'output_limit_unverified');spawn.assert_not_called()

    def test_approved_once_is_recorded_and_a_second_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.freeze(directory)
            def response(claude,prompt,schema,data,deadline,cancel,output_mode,*,approved_once):
                self.assertTrue(approved_once)
                role='check' if 'original_request' in data else 'generate'
                return fixed.SupplementalFixedPlanTests.response(role,prompt,schema,data,deadline,cancel)
            account=dict(loggedIn=True,authMethod='claude.ai',apiProvider='firstParty')
            with patch.object(launch,'subscription_account',return_value=account) as auth, \
                    patch.object(qa,'call',side_effect=response) as call:
                report=launch.run(root,claude='fake',approved_once=True,clock=lambda:0)
                self.assertEqual(call.call_count,41);auth.assert_called_once()
                self.assertTrue(report['preparation']['actual_execution_authorized'])
                self.assertTrue(json.loads((root/'run-started.json').read_bytes())['approved_once'])
                with self.assertRaises(FileExistsError):
                    launch.run(root,claude='fake',approved_once=True)
                self.assertEqual(call.call_count,41);auth.assert_called_once()
            self.assertFalse(qa.output_readiness('text-json')['actual_execution_authorized'])

    def test_default_and_other_plans_do_not_gain_execution_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.freeze(directory)
            with patch.object(launch,'subscription_account') as auth, patch.object(qa,'call') as call:
                for approval in (False,1,'yes'):
                    with self.subTest(approval=approval),self.assertRaises(ValueError):
                        launch.run(root,approved_once=approval)
                self.assertFalse((root/'run-started.json').exists())
                auth.assert_not_called();call.assert_not_called()
        for kind in ('launch','supplemental','supplemental-fixed'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError,'approval is only'):
                    self.freeze(directory,plan_kind=kind)
                self.assertFalse((Path(directory)/'approved').exists())
        with tempfile.TemporaryDirectory() as directory:
            root,_=fixed.SupplementalFixedPlanTests.freeze(self,directory)
            with patch.object(launch,'subscription_account') as auth,patch.object(qa,'call') as call:
                with self.assertRaisesRegex(ValueError,'approval is only'):
                    launch.run(root,approved_once=True)
                auth.assert_not_called();call.assert_not_called()

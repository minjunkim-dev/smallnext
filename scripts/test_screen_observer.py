"""Offline QA-state and subprocess cleanup checks; no simulator or model use."""
from pathlib import Path
from contextlib import closing
import sqlite3
import os
import json
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import oauth_quality as qa

from screen_evaluation import slots
from screen_observer import Observer


class ScreenObserverTests(unittest.TestCase):
    def test_relocated_app_cache_and_export_share_remaining_observation_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            old, new = directory / 'old-container', directory / 'new-container'
            (new / 'Library/Caches').mkdir(parents=True)
            sample = {'runID': 'current-uuid'}
            (new / 'Library/Caches/suggestion-timing.json').write_text(json.dumps([sample]))
            configuration = directory / 'test.xctestrun'
            configuration.write_bytes(plistlib.dumps({'target': {'TestBundlePath': '__TESTROOT__/dummy'}}))
            observer = Observer(directory, 'fake-simulator', configuration, 'http://127.0.0.1:58114')
            now, reads = [0], []
            image = b'\x89PNG\r\n\x1a\nfixture'
            observation = {'method': 'XCTest-visible-fixture', 'run_id': 'current-uuid',
                           'evidence_sha256': qa.digest(image)}
            def command(argv, *, timeout=30, log=None):
                if 'get_app_container' in argv:
                    reads.append(timeout)
                    return str(old if len(reads) == 1 else new)
                if argv[0] == 'xcodebuild':
                    (directory / '00.xcresult').mkdir()
                    now[0] += 179
                    return 0
                self.assertLessEqual(timeout, 1)
                exported = directory / '00-attachments'
                exported.mkdir()
                (exported / 'observation.json').write_text(json.dumps(observation))
                (exported / 'screen.png').write_bytes(image)
                return ''
            with patch.object(observer, 'command', side_effect=command), patch.object(observer, 'prepare'), \
                    patch('screen_observer.monotonic', side_effect=lambda: now[0]), \
                    patch('screen_observer.subprocess.run') as terminate:
                result = observer(0, slots()[0], 180)
            self.assertEqual(result[1], sample)
            self.assertEqual(len(reads), 2)
            self.assertLessEqual(reads[-1], 1)
            self.assertLessEqual(terminate.call_args.kwargs['timeout'], 1)

    def test_independent_synthetic_seeds_preserve_older_goals_and_never_complete_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database = directory / 'qa.sqlite'
            with closing(sqlite3.connect(database)) as db, db:
                db.executescript('''CREATE TABLE goal(id INTEGER PRIMARY KEY, statement,current_state,materials,
                    available_minutes,is_confirmed,completion_criteria,proposed_completion_criteria,status,revision,created_at,updated_at);
                    CREATE TABLE app_metadata(key PRIMARY KEY,value);
                    CREATE TABLE suggestion_request(goal_id,kind,goal_revision,status,created_at);
                    CREATE TABLE action(goal_id,task,done_when,estimated_minutes,reason,status,sequence,material_links);''')
            observer = Observer(directory, 'not-used', directory / 'not-used', 'http://127.0.0.1:58114')
            observer.database = database
            for index, slot in enumerate(slots()):
                observer.prepare(slot)
                with closing(sqlite3.connect(database)) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM goal').fetchone()[0], index + 1)
                    selected = int(db.execute("SELECT value FROM app_metadata WHERE key='selected_goal_id'").fetchone()[0])
                    first = slot['input']['request_kind'] == 'first_action'
                    self.assertEqual(db.execute('SELECT is_confirmed FROM goal WHERE id=?', (selected,)).fetchone()[0], not first)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM action WHERE goal_id=?', (selected,)).fetchone()[0], not first)
                    self.assertFalse(db.execute("SELECT * FROM action WHERE status='done'").fetchall())

    def test_timed_out_observer_command_is_reaped_and_log_is_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            observer = Observer(directory, 'not-used', directory / 'not-used', 'http://127.0.0.1:58114')
            log = directory / 'observer.log'
            with self.assertRaises(subprocess.TimeoutExpired):
                observer.command([sys.executable, '-c', 'import time;time.sleep(30)'], timeout=.05, log=log)
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                observer.command([sys.executable, '-c', 'pass'], log=log)

    def test_timeout_kills_descendant_when_leader_exits_on_term(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / 'child.pid'
            program = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
            leader = ('import subprocess,sys,time;from pathlib import Path;'
                      f'child=subprocess.Popen([sys.executable,"-c",{program!r}]);'
                      f'Path({str(marker)!r}).write_text(str(child.pid));time.sleep(30)')
            observer = Observer(directory, 'not-used', directory / 'not-used', '')
            pid = None
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    observer.command([sys.executable, '-c', leader], timeout=.3, log=directory / 'command.log')
                pid = int(marker.read_text())
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    status = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True).stdout.strip()
                    if not status or status.startswith('Z'):
                        break
                    time.sleep(.02)
                self.assertTrue(not status or status.startswith('Z'), status)
            finally:
                if pid is not None:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == '__main__':
    unittest.main()

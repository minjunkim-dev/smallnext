"""Local #111 observer using the existing TimingValidation scheme and QA simulator only."""
import json
from contextlib import closing
import errno
import os
from pathlib import Path
import plistlib
import signal
import sqlite3
import subprocess
import sys
from time import monotonic, sleep

import oauth_quality as qa


class Observer:
    def __init__(self, directory, simulator, xctestrun, url, *, mock_only=False):
        self.directory, self.simulator = Path(directory), simulator
        self.xctestrun, self.url = Path(xctestrun), url
        self.mock_only = mock_only

    def command(self, argv, *, timeout=30, log=None):
        if log is None:
            return subprocess.check_output(argv, timeout=timeout).decode().strip()
        with log.open('xb') as output:
            os.chmod(log, 0o600)
            child = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = monotonic() + timeout
                while True:
                    if (self.directory / 'stopped.json').exists():
                        raise ValueError('screen run stopped')
                    try:
                        return child.wait(timeout=max(.001, min(.1, deadline - monotonic())))
                    except subprocess.TimeoutExpired:
                        if monotonic() >= deadline:
                            raise
            except BaseException:
                # Keep the leader unreaped until both signals, even if TERM ends it first.
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(child.pid, sig)
                    except (ProcessLookupError, PermissionError):
                        # macOS may report EPERM for a group containing only the unreaped leader.
                        pass
                    if sig == signal.SIGTERM:
                        sleep(.05)
                child.wait(timeout=1)
                raise

    def preflight(self):
        devices = json.loads(self.command(['xcrun', 'simctl', 'list', 'devices', '-j']))['devices']
        selected = [device for runtime, rows in devices.items() if runtime.endswith('iOS-27-0')
                    for device in rows if device['udid'] == self.simulator]
        if len(selected) != 1 or not selected[0]['name'].startswith('Smallnext111-'):
            raise ValueError('fresh dedicated Smallnext111 iOS 27.0 simulator required')
        self.refresh_container()
        if not self.database.is_file():
            raise ValueError('initialize the empty QA app without a development URL first')
        with closing(sqlite3.connect(f'file:{self.database}?mode=rw', uri=True)) as db:
            if db.execute('SELECT COUNT(*) FROM goal').fetchone()[0]:
                raise ValueError('QA simulator must start with no goals')

    def refresh_container(self, timeout=30):
        # XCTest installation can move the preserved app data to a new container UUID.
        self.container = Path(self.command(['xcrun', 'simctl', 'get_app_container', self.simulator,
                                            'dev.smallnext.app', 'data'], timeout=timeout))
        self.database = self.container / 'Library/Application Support/Smallnext/smallnext.sqlite'

    def prepare(self, slot):
        # Only insert new synthetic goals into this run's empty QA database; never erase a goal.
        with closing(sqlite3.connect(f'file:{self.database}?mode=rw', uri=True)) as db, db:
            first = slot['input']['request_kind'] == 'first_action'
            cursor = db.execute('''INSERT INTO goal
                (statement,current_state,materials,available_minutes,is_confirmed,completion_criteria,
                 proposed_completion_criteria,status,revision,created_at,updated_at)
                VALUES (?,?,?,5,?,?,?,'active',0,datetime('now'),datetime('now'))''',
                (slot['goal'], slot['facts'], '[]', not first, None if first else slot['criteria'],
                 slot['criteria'] if first else None))
            goal_id = cursor.lastrowid
            db.execute("INSERT INTO app_metadata(key,value) VALUES ('selected_goal_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (str(goal_id),))
            if first:
                db.execute("INSERT INTO suggestion_request(goal_id,kind,goal_revision,status,created_at) VALUES (?,'goal_preparation',0,'applied',datetime('now'))",
                           (goal_id,))
            else:
                db.execute('''INSERT INTO action
                    (goal_id,task,done_when,estimated_minutes,reason,status,sequence,material_links)
                    VALUES (?,?,?,5,'합성 미완료 seed','current',1,'[]')''',
                    (goal_id, slot['goal'], slot['criteria']))

    def __call__(self, index, slot, budget):
        started = monotonic()
        def remaining(maximum):
            value = budget - (monotonic() - started)
            if value <= 0:
                raise TimeoutError('screen observation budget exhausted')
            return min(maximum, value)
        self.refresh_container(timeout=remaining(30))
        self.prepare(slot)
        result = self.directory / f'{index:02d}.xcresult'
        exported = self.directory / f'{index:02d}-attachments'
        configuration = plistlib.loads(self.xctestrun.read_bytes())

        def configure(value):
            if isinstance(value, dict):
                value = {key: configure(item) for key, item in value.items()}
                if 'TestBundlePath' in value:
                    value['EnvironmentVariables'] = dict(value.get('EnvironmentVariables', {}),
                        SMALLNEXT_SCREEN_ONCE='1', SMALLNEXT_SCREEN_KIND=slot['input']['request_kind'],
                        SMALLNEXT_TIMING_TEST_URL=self.url, SMALLNEXT_SCREEN_MOCK='1' if self.mock_only else '0')
                return value
            if isinstance(value, list):
                return [configure(item) for item in value]
            return value.replace('__TESTROOT__', str(self.xctestrun.parent)) if isinstance(value, str) else value

        test_file = self.directory / f'{index:02d}.xctestrun'
        with test_file.open('xb') as stream:
            os.chmod(test_file, 0o600)
            plistlib.dump(configure(configuration), stream)
        try:
            code = self.command(['xcodebuild', '-xctestrun', str(test_file), '-destination',
                f'platform=iOS Simulator,id={self.simulator}', '-resultBundlePath', str(result),
                '-parallel-testing-enabled', 'NO',
                '-only-testing:SmallnextTimingUITests/ScreenTimingTests/testApprovedSingleScreen',
                'test-without-building'], timeout=remaining(180),
                log=self.directory / f'{index:02d}-xcodebuild.log')
            if code:
                raise ValueError('screen observation failed; no retry')
            self.command(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', str(result),
                          '--output-path', str(exported)], timeout=remaining(30))
            observations = []
            for path in exported.glob('*.json'):
                value = json.loads(path.read_bytes())
                if isinstance(value, dict) and value.get('method', '').startswith('XCTest-visible'):
                    observations.append(value)
            if len(observations) != 1:
                raise ValueError('one UUID-linked screen observation required')
            observation = observations[0]
            self.refresh_container(timeout=remaining(30))
            cache = json.loads((self.container / 'Library/Caches/suggestion-timing.json').read_bytes())
            app = [sample for sample in cache if sample.get('runID') == observation['run_id']]
            images = [path.read_bytes() for path in exported.glob('*.png')
                      if qa.digest(path.read_bytes()) == observation['evidence_sha256']]
            if len(app) != 1 or len(images) != 1:
                raise ValueError('UUID cache or PNG missing')
            qa.save(self.directory / f'{index:02d}-app-cache.json', cache)
            remaining(180)
            for tree in (result, exported):
                for parent, directories, files in os.walk(tree):
                    os.chmod(parent, 0o700)
                    for name in directories:
                        path = Path(parent) / name
                        if path.is_symlink():
                            raise ValueError('unexpected evidence symlink')
                        os.chmod(path, 0o700)
                    for name in files:
                        path = Path(parent) / name
                        if path.is_symlink():
                            raise ValueError('unexpected evidence symlink')
                        os.chmod(path, 0o600)
            return observation, app[0], images[0]
        finally:
            # The QA app owns the HTTP request; terminating it disconnects Rust's CLI worker.
            failed = sys.exc_info()[0] is not None
            try:
                result = subprocess.run(['xcrun', 'simctl', 'terminate', self.simulator, 'dev.smallnext.app'],
                                        capture_output=True, timeout=max(.01, min(15, budget - (monotonic() - started))), check=False)
                already_stopped = (result.returncode == errno.ESRCH
                                   and b'found nothing to terminate' in result.stderr)
                if result.returncode != 0 and not already_stopped:
                    raise subprocess.CalledProcessError(result.returncode, result.args)
            except (OSError, subprocess.SubprocessError) as error:
                try:
                    qa.save(self.directory / f'{index:02d}-cleanup.json',
                            {'error': 'terminate_timeout' if isinstance(error, subprocess.TimeoutExpired) else 'terminate_failed'})
                except OSError:
                    pass  # Keep the primary failure even when its secondary diagnostic cannot be written.
                if not failed:
                    raise

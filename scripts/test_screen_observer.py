"""Offline QA-state and subprocess cleanup checks; no simulator or model use."""
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from screen_evaluation import slots
from screen_observer import Observer


class ScreenObserverTests(unittest.TestCase):
    def test_independent_synthetic_seeds_preserve_older_goals_and_never_complete_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database = directory / 'qa.sqlite'
            with sqlite3.connect(database) as db:
                db.executescript('''CREATE TABLE goal(id INTEGER PRIMARY KEY, statement,current_state,materials,
                    available_minutes,is_confirmed,completion_criteria,proposed_completion_criteria,status,revision,created_at,updated_at);
                    CREATE TABLE app_metadata(key PRIMARY KEY,value);
                    CREATE TABLE suggestion_request(goal_id,kind,goal_revision,status,created_at);
                    CREATE TABLE action(goal_id,task,done_when,estimated_minutes,reason,status,sequence,material_links);''')
            observer = Observer(directory, 'not-used', directory / 'not-used', 'http://127.0.0.1:58114')
            observer.database = database
            for index, slot in enumerate(slots()):
                observer.prepare(slot)
                with sqlite3.connect(database) as db:
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


if __name__ == '__main__':
    unittest.main()

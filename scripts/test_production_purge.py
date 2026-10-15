import subprocess
import unittest
from unittest.mock import patch

import check_production_purge as purge


class ProductionPurgeTests(unittest.TestCase):
    def test_timeout_removes_the_oneoff_container(self):
        timeout = subprocess.TimeoutExpired('docker', 90)
        with patch.object(purge.subprocess, 'run', side_effect=[timeout, None]) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                purge.run(['--rm', 'test-image'], {})
        created = run.call_args_list[0].args[0]
        removed = run.call_args_list[1].args[0]
        self.assertEqual(removed, ['docker', 'rm', '--force', created[3]])

    def test_failure_does_not_expose_database_diagnostics(self):
        secret = 'test-private-database-diagnostic'
        failure = subprocess.CompletedProcess('docker', 1, secret, secret)
        with patch.object(purge.subprocess, 'run', side_effect=[failure, None]):
            with self.assertRaises(RuntimeError) as caught:
                purge.run(['--rm', 'test-image'], {})
        self.assertNotIn(secret, str(caught.exception))


if __name__ == '__main__':
    unittest.main()

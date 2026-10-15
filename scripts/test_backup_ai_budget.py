import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import backup_ai_budget as backup
from prepare_production import save_private


NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def value():
    return {'schema_version': 1, 'created_at': NOW.strftime(backup.UTC_STAMP),
            'budget': {'month': '2026-10', 'charged_micro_usd': 123, 'blocked': False}}


class SnapshotValidationTests(unittest.TestCase):
    def test_valid_empty_and_old_month(self):
        for budget in [None, {'month': '2026-09', 'charged_micro_usd': backup.MAX_I64, 'blocked': True}]:
            backup.validate(dict(value(), budget=budget), NOW)

    def test_rejects_types_unknown_fields_future_and_out_of_range(self):
        changes = [('schema_version', True), ('schema_version', 2),
                   ('created_at', '2026-10-16T12:00:00+00:00'),
                   ('created_at', '2026-10-17T12:00:00.000000Z'), ('extra', 'private')]
        for field, item in changes:
            candidate = dict(value(), **{field: item})
            with self.subTest(field=field, item=item), self.assertRaises(ValueError):
                backup.validate(candidate, NOW)
        for field, item in [('month', '2026-00'), ('month', '2026-11'), ('month', 202610),
                            ('charged_micro_usd', -1), ('charged_micro_usd', True),
                            ('charged_micro_usd', 1.0), ('charged_micro_usd', backup.MAX_I64 + 1),
                            ('blocked', 0), ('extra', 'private')]:
            candidate = copy.deepcopy(value())
            candidate['budget'][field] = item
            with self.subTest(field=field, item=item), self.assertRaises(ValueError):
                backup.validate(candidate, NOW)

    def test_rejects_duplicate_missing_corrupt_and_oversized_json(self):
        for data in ['{"budget":null,"budget":null}', '{', 'NaN', ' ' * (backup.MAX_PLAINTEXT + 1)]:
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                backup.validate(backup.load_json(data), NOW)
        for field in value():
            candidate = value()
            del candidate[field]
            with self.assertRaises(ValueError):
                backup.validate(candidate, NOW)

    def test_database_url_is_only_in_process_environment(self):
        secret = 'postgres://test:private%20%27%24%28%29@db.invalid:5433/test?options=-csearch_path%3Dtest_schema&sslmode=verify-full'
        with patch.dict(os.environ, {'BACKUP_DATABASE_URL': secret}, clear=True):
            with patch.object(backup, 'docker_run', return_value='') as run:
                backup.database('BACKUP_DATABASE_URL', 'host')('SELECT 1')
        self.assertNotIn(secret, str(run.call_args.args[0]))
        self.assertNotIn('private', str(run.call_args.args[0]))
        self.assertNotIn('sh', run.call_args.args[0])
        env = run.call_args.args[1]
        self.assertEqual("private '$()", env['PGPASSWORD'])
        self.assertEqual('test', env['PGDATABASE'])
        self.assertEqual('5433', env['PGPORT'])
        self.assertEqual('verify-full', env['PGSSLMODE'])
        self.assertEqual('-csearch_path=test_schema', env['PGOPTIONS'])

    def test_database_rejects_unknown_and_duplicate_dsn_options(self):
        for query in ['service=other', 'options=a&options=b']:
            with patch.dict(os.environ, {'BACKUP_DATABASE_URL': 'postgres://test@db.invalid/test?' + query}, clear=True):
                with self.assertRaises(ValueError):
                    backup.database('BACKUP_DATABASE_URL', 'host')


class PrivatePathTests(unittest.TestCase):
    def test_rejects_git_paths_symlinks_and_public_modes(self):
        with self.assertRaises(ValueError):
            backup.external(backup.ROOT / 'work' / 'backup')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            private = root / 'private'
            save_private(private, 'public recipient')
            link = root / 'link'
            link.symlink_to(private)
            with self.assertRaises(ValueError):
                backup.private_file(link, 100)
            private.chmod(0o644)
            with self.assertRaises(ValueError):
                backup.private_file(private, 100)
            nested = root / 'nested'
            nested.mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                backup.private_directory(nested)


@unittest.skipUnless(shutil.which('age') and shutil.which('age-keygen'), 'requires standard age CLI')
class EncryptedBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.directory = backup.private_directory(self.root / 'backups')
        self.keys = backup.private_directory(self.root / 'keys')
        self.identity = self.keys / 'identity.txt'
        generated = subprocess.run(['age-keygen'], capture_output=True, check=True).stdout.decode()
        save_private(self.identity, generated)
        self.recipients = self.keys / 'recipients.txt'
        public = subprocess.run(['age-keygen', '--y', str(self.identity)], capture_output=True, check=True).stdout.decode()
        save_private(self.recipients, public)

    def create(self, candidate=None, now=NOW):
        candidate = candidate or value()
        row = json.dumps(candidate['budget']) if candidate['budget'] is not None else ''
        return backup.snapshot(self.directory, self.recipients, now=now, sql=lambda _: row)

    def test_age_roundtrip_is_atomic_private_and_ciphertext_only(self):
        path = self.create()
        self.assertEqual(backup.decrypt(path, self.identity, NOW), value())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b'charged_micro_usd', path.read_bytes())
        self.assertEqual([path], list(self.directory.iterdir()))
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            self.create()
        self.assertEqual(original, path.read_bytes())

    def test_age_authentication_rejects_tampering_and_wrong_key(self):
        path = self.create()
        other = self.keys / 'wrong-key.txt'
        save_private(other, subprocess.run(['age-keygen'], capture_output=True, check=True).stdout.decode())
        with self.assertRaises(RuntimeError):
            backup.decrypt(path, other, NOW)
        content = bytearray(path.read_bytes())
        position = content.index(b'\n') + 5
        content[position] = ord('A') if content[position] != ord('A') else ord('B')
        path.write_bytes(content)
        with self.assertRaises(RuntimeError):
            backup.decrypt(path, self.identity, NOW)

    def test_empty_backup_and_identity_separation(self):
        path = self.create(dict(value(), budget=None))
        self.assertIsNone(backup.decrypt(path, self.identity, NOW)['budget'])
        inside = self.directory / 'identity.txt'
        save_private(inside, self.identity.read_text())
        with self.assertRaises(ValueError):
            backup.decrypt(path, inside, NOW)
        with self.assertRaises(ValueError):
            backup.snapshot(self.directory, self.identity, now=NOW, sql=lambda _: '')

    def test_seven_day_expiration_uses_creation_name_not_copy_mtime(self):
        old = self.create(now=NOW - timedelta(days=7))
        recent = self.create(now=NOW - timedelta(days=6))
        os.utime(old, (NOW.timestamp(), NOW.timestamp()))
        os.utime(recent, (0, 0))
        foreign = self.directory / 'unrelated.age'
        save_private(foreign, 'leave this file')
        self.assertEqual(backup.expire(self.directory, NOW), 1)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(foreign.exists())

    @unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires explicit isolated TEST_DATABASE_URL')
    def test_real_database_snapshot_and_isolated_restore(self):
        sql = backup.database('TEST_DATABASE_URL', 'host')
        schema = f'test_backup_source_{uuid4().hex}'
        sql(f'CREATE SCHEMA {schema};')
        self.addCleanup(lambda: sql(f'DROP SCHEMA {schema} CASCADE;'))
        migrations = '\n'.join((backup.ROOT / f'services/api/migrations/{name}').read_text()
                               for name in ['0002_ai_budget.sql', '0003_ai_budget_blocked.sql'])
        sql(f'''SET search_path TO {schema}; {migrations}
            INSERT INTO ai_budget (month, charged_micro_usd, blocked)
            VALUES (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM'), 123, FALSE);''')
        parts = urlsplit(os.environ['TEST_DATABASE_URL'])
        query = parse_qsl(parts.query)
        query.append(('options', f'-csearch_path={schema}'))
        with patch.dict(os.environ, {'BACKUP_DATABASE_URL': urlunsplit(parts._replace(query=urlencode(query)))}):
            path = backup.snapshot(self.directory, self.recipients)
        self.assertEqual(backup.decrypt(path, self.identity)['budget']['charged_micro_usd'], 123)
        backup.check_restore(path, self.identity)


if __name__ == '__main__':
    unittest.main()

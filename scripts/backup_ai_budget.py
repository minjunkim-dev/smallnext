#!/usr/bin/env python3
"""Encrypt budget-only snapshots; restore checks use isolated test schemas only."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import uuid4

from check_production_purge import POSTGRES_IMAGE, run as docker_run
from prepare_production import save_private


ROOT = Path(__file__).resolve().parents[1]
MAX_PLAINTEXT = 4096
MAX_ENCRYPTED = 16384
MAX_I64 = 2**63 - 1
NAME = re.compile(r'ai-budget-(\d{8}T\d{12}Z)\.age')
STAMP = '%Y%m%dT%H%M%S%fZ'
UTC_STAMP = '%Y-%m-%dT%H:%M:%S.%fZ'


def utc_now():
    return datetime.now(timezone.utc)


def external(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink() or (parent / '.git').exists():
            raise ValueError('use a path outside Git without symlinks')
    return path


def private_directory(path):
    path = external(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
        raise ValueError('private directory requires owner-only mode 0700')
    return path


def private_file(path, limit):
    path = external(path)
    private_directory(path.parent)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid() or not 0 < info.st_size <= limit):
        raise ValueError('private file requires mode 0600 and bounded size')
    return path


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def load_json(data):
    if len(data) > MAX_PLAINTEXT:
        raise ValueError('snapshot exceeds size limit')
    return json.loads(data, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid number')))


def validate(value, now=None):
    now = now or utc_now()
    if type(value) is not dict or set(value) != {'schema_version', 'created_at', 'budget'}:
        raise ValueError('invalid snapshot fields')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('unsupported snapshot version')
    created = value['created_at']
    if type(created) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z', created):
        raise ValueError('created_at must be UTC')
    created = datetime.strptime(created, UTC_STAMP).replace(tzinfo=timezone.utc)
    if created > now:
        raise ValueError('future snapshot timestamp')
    budget = value['budget']
    if budget is not None:
        if type(budget) is not dict or set(budget) != {'month', 'charged_micro_usd', 'blocked'}:
            raise ValueError('invalid budget fields')
        month, charged, blocked = budget['month'], budget['charged_micro_usd'], budget['blocked']
        if type(month) is not str or not re.fullmatch(r'\d{4}-\d{2}', month):
            raise ValueError('invalid UTC month')
        datetime.strptime(month, '%Y-%m')
        if month > created.strftime('%Y-%m'):
            raise ValueError('future budget month')
        if type(charged) is not int or not 0 <= charged <= MAX_I64 or type(blocked) is not bool:
            raise ValueError('invalid budget amount or block')
    return created


def age(args, data):
    result = subprocess.run(['age', *args], input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30)
    if result.returncode:
        raise RuntimeError('age operation failed')
    return result.stdout


def database(environment, network):
    url = os.environ.get(environment)
    if not url:
        raise ValueError('explicit database environment is required')
    parts = urlsplit(url)
    if parts.scheme not in {'postgres', 'postgresql'} or not parts.hostname or parts.fragment:
        raise ValueError('invalid PostgreSQL connection URL')
    query = unique_object(parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)) if parts.query else {}
    if set(query) - {'sslmode', 'sslrootcert', 'options'}:
        raise ValueError('unsupported PostgreSQL connection option')
    values = {'PGHOST': parts.hostname, 'PGPORT': str(parts.port or 5432),
              'PGDATABASE': unquote(parts.path.removeprefix('/'), errors='strict')}
    if parts.username is not None:
        values['PGUSER'] = unquote(parts.username, errors='strict')
    if parts.password is not None:
        values['PGPASSWORD'] = unquote(parts.password, errors='strict')
    for key, variable in [('sslmode', 'PGSSLMODE'), ('options', 'PGOPTIONS')]:
        if key in query:
            values[variable] = query[key]
    mounts = []
    ca_file = os.environ.get('BACKUP_SSL_ROOT_CERT_FILE' if environment == 'BACKUP_DATABASE_URL'
                             else 'TEST_SSL_ROOT_CERT_FILE') or query.get('sslrootcert')
    if ca_file:
        ca_file = private_file(ca_file, 65536)
        if ',' in str(ca_file):
            raise ValueError('unsupported certificate path')
        mounts = ['--mount', f'type=bind,source={ca_file},target=/run/db-ca.pem,readonly']
        values['PGSSLROOTCERT'] = '/run/db-ca.pem'
    env = dict(os.environ, **values)
    forwarded = [item for key in values for item in ['--env', key]]
    args = ['--rm', '--interactive', '--network', network, *mounts, *forwarded,
            POSTGRES_IMAGE, 'psql', '-X', '-qAt', '--set', 'ON_ERROR_STOP=1']
    return lambda statement: docker_run(args, env, sql=statement)


def expire(directory, now=None):
    directory = private_directory(directory)
    cutoff = (now or utc_now()) - timedelta(days=7)
    removed = 0
    for path in directory.iterdir():
        match = NAME.fullmatch(path.name)
        if match:
            private_file(path, MAX_ENCRYPTED)
            created = datetime.strptime(match[1], STAMP).replace(tzinfo=timezone.utc)
            if created <= cutoff:
                path.unlink()
                removed += 1
    return removed


def snapshot(directory, recipients_file, network='host', *, now=None, sql=None):
    now = now or utc_now()
    directory = private_directory(directory)
    expire(directory, now)
    recipients_file = private_file(recipients_file, MAX_ENCRYPTED)
    if b'AGE-SECRET-KEY-' in recipients_file.read_bytes():
        raise ValueError('server requires public recipients only')
    sql = sql or database('BACKUP_DATABASE_URL', network)
    row = sql("SELECT json_build_object('month', month, 'charged_micro_usd', charged_micro_usd, 'blocked', blocked) FROM ai_budget;")
    value = {'schema_version': 1, 'created_at': now.strftime(UTC_STAMP),
             'budget': load_json(row) if row else None}
    validate(value, now)
    plaintext = json.dumps(value, separators=(',', ':')).encode()
    encrypted = age(['--encrypt', '--armor', '--recipients-file', str(recipients_file)], plaintext)
    if len(encrypted) > MAX_ENCRYPTED:
        raise ValueError('encrypted snapshot exceeds size limit')
    target = directory / f'ai-budget-{now.strftime(STAMP)}.age'
    if target.exists() or target.is_symlink():
        raise ValueError('snapshot already exists')
    save_private(target, encrypted.decode('ascii'))
    return target


def decrypt(path, identity_file, now=None):
    path = private_file(path, MAX_ENCRYPTED)
    identity_file = private_file(identity_file, MAX_ENCRYPTED)
    if path.parent == identity_file.parent or path.parent in identity_file.parents:
        raise ValueError('identity must be separate from backup directory')
    match = NAME.fullmatch(path.name)
    if not match:
        raise ValueError('invalid snapshot filename')
    value = load_json(age(['--decrypt', '--identity', str(identity_file)], path.read_bytes()))
    created = validate(value, now)
    if created.strftime(STAMP) != match[1]:
        raise ValueError('snapshot filename timestamp differs')
    if created <= (now or utc_now()) - timedelta(days=7):
        raise ValueError('snapshot has expired')
    return value


def restore_check_sql(value):
    # Only the isolated checker calls this; an old/empty backup must never reopen AI.
    validate(value)
    amount = value['budget']['charged_micro_usd'] if value['budget'] else 0
    return f"""INSERT INTO ai_budget (singleton, month, charged_micro_usd, blocked)
        VALUES (TRUE, to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM'), {amount}, TRUE)
        ON CONFLICT (singleton) DO UPDATE SET month=EXCLUDED.month,
            charged_micro_usd=GREATEST(ai_budget.charged_micro_usd, EXCLUDED.charged_micro_usd),
            blocked=ai_budget.blocked OR EXCLUDED.blocked;"""


def check_restore(path, identity_file, network='host'):
    value = decrypt(path, identity_file)
    sql = database('TEST_DATABASE_URL', network)
    schema = f'test_budget_restore_{uuid4().hex}'
    sql(f'CREATE SCHEMA {schema};')
    try:
        # Only budget tables are needed; never replay permission changes on a shared DB.
        migrations = '\n'.join((ROOT / f'services/api/migrations/{name}').read_text()
                               for name in ['0002_ai_budget.sql', '0003_ai_budget_blocked.sql'])
        sql(f'SET search_path TO {schema}; {migrations}')
        original = value['budget']['charged_micro_usd'] if value['budget'] else 0
        old = {'schema_version': 1, 'created_at': utc_now().strftime(UTC_STAMP),
               'budget': {'month': '2000-01', 'charged_micro_usd': 1, 'blocked': False}}
        empty = dict(old, budget=None)
        for candidate in [value, old, empty]:
            amount = candidate['budget']['charged_micro_usd'] if candidate['budget'] else 0
            sql(f'SET search_path TO {schema}; DELETE FROM ai_budget; {restore_check_sql(candidate)}')
            actual = sql(f'''SET search_path TO {schema};
                SELECT month=to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM')
                    AND charged_micro_usd={amount} AND blocked FROM ai_budget;''')
            if actual != 't':
                raise RuntimeError('empty target restore did not preserve budget')
            sql(f'''SET search_path TO {schema}; DELETE FROM ai_budget;
                INSERT INTO ai_budget (month, charged_micro_usd, blocked)
                VALUES (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM'), {max(original, 500)}, FALSE);
                {restore_check_sql(candidate)}''')
            actual = sql(f'''SET search_path TO {schema};
                SELECT month=to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM')
                    AND charged_micro_usd={max(original, 500)} AND blocked FROM ai_budget;''')
            if actual != 't':
                raise RuntimeError('restore did not preserve cost and block')
            sql(f'SET search_path TO {schema}; {restore_check_sql(empty)}')
            if sql(f'SET search_path TO {schema}; SELECT blocked FROM ai_budget;') != 't':
                raise RuntimeError('restore cleared existing block')
        print('PASS isolated budget restore: current UTC month blocked; cost never reduced')
    finally:
        sql(f'DROP SCHEMA {schema} CASCADE;')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('snapshot')
    create.add_argument('--directory', required=True)
    create.add_argument('--recipients-file', required=True)
    create.add_argument('--network', default='host')
    cleanup = commands.add_parser('expire')
    cleanup.add_argument('--directory', required=True)
    restore = commands.add_parser('check-restore')
    restore.add_argument('snapshot')
    restore.add_argument('--identity-file', required=True)
    restore.add_argument('--network', default='host')
    args = parser.parse_args()
    try:
        if args.command == 'snapshot':
            snapshot(args.directory, args.recipients_file, args.network)
            print('PASS encrypted budget snapshot; expired snapshots removed')
        elif args.command == 'expire':
            expire(args.directory)
            print('PASS budget snapshot expiration')
        else:
            check_restore(args.snapshot, args.identity_file, args.network)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        print('Budget backup operation failed; verify private files, age and database access', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

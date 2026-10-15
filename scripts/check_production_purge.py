#!/usr/bin/env python3
"""Run the production image's purge binary against an isolated test DB schema."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_IMAGE = (
    'postgres:18-alpine@sha256:'
    '77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873'
)


def run(args, env, *, sql=None):
    name = f'smallnext-purge-check-{uuid4().hex}'
    try:
        result = subprocess.run(['docker', 'run', '--name', name, *args],
                                env=env, input=sql, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=90)
    finally:
        # A timed-out Docker client can leave its container running.
        subprocess.run(['docker', 'rm', '--force', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)
    if result.returncode:
        raise RuntimeError('production purge check command failed')
    return result.stdout.strip()


def check(image, network):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        raise RuntimeError('set TEST_DATABASE_URL to an isolated test database')
    schema = f'test_image_purge_{uuid4().hex}'
    base = ['--rm', '--interactive', '--network', network]
    # psql expands a URI only with explicit dbname; pass the env value inside the client.
    client = [*base, '--env', 'PGDATABASE', POSTGRES_IMAGE,
              'sh', '-c', 'exec psql --dbname "$PGDATABASE" -X -qAt --set ON_ERROR_STOP=1']
    client_env = dict(os.environ, PGDATABASE=url)

    def sql(statement):
        return run(client, client_env, sql=statement)

    sql(f'CREATE SCHEMA {schema};')
    try:
        migrations = '\n'.join(path.read_text() for path in
                               sorted((ROOT / 'services/api/migrations').glob('*.sql')))
        # Manual migration replay needs the metadata table normally created by SQLx.
        sql(f'''SET search_path TO {schema};
            CREATE TABLE _sqlx_migrations (
                version BIGINT PRIMARY KEY, description TEXT NOT NULL,
                installed_on TIMESTAMPTZ NOT NULL DEFAULT now(), success BOOLEAN NOT NULL,
                checksum BYTEA NOT NULL, execution_time BIGINT NOT NULL
            );
            {migrations}''')
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        options = ' '.join(value for key, value in query if key == 'options')
        query = [(key, value) for key, value in query if key != 'options']
        query.append(('options', f'{options} -csearch_path={schema}'.strip()))
        isolated_url = urlunsplit(parts._replace(query=urlencode(query)))
        purge_env = dict(os.environ, DATABASE_URL=isolated_url)
        for offset, count in [(-1, '0'), (0, '1'), (1, '1')]:
            sql(f"""SET search_path TO {schema};
                TRUNCATE ai_budget;
                INSERT INTO ai_budget (month, charged_micro_usd, blocked)
                VALUES (to_char((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
                    + INTERVAL '{offset} month', 'YYYY-MM'), 123, TRUE);""")
            output = run([*base, '--env', 'DATABASE_URL', '--entrypoint',
                          'purge-ai-budget', image], purge_env)
            assert output == 'AI budget purge completed', 'purge success log missing'
            actual = sql(f'SET search_path TO {schema}; SELECT count(*) FROM ai_budget;')
            assert actual == count, f'UTC month offset {offset}: unexpected row count'
        print('Production image purge: previous month deleted; current/future months retained')
    finally:
        sql(f'DROP SCHEMA {schema} CASCADE;')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='smallnext-api:ci')
    parser.add_argument('--network', default='host')
    args = parser.parse_args()
    try:
        check(args.image, args.network)
    except (AssertionError, OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        # Connection URLs and database diagnostics must not enter CI or host logs.
        print('Production image purge check failed; verify the test DB and image', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

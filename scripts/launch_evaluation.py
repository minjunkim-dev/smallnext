#!/usr/bin/env python3
"""Opt-in, sequential launch QA. Paid transport is deliberately unavailable."""
import argparse
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import selectors
import statistics
import stat
import subprocess
import threading
from time import monotonic
import uuid

import oauth_quality as qa


LIMITS = {'requests': 81, 'calls': 162, 'seconds': 5400,
          'initial_micro_usd': 3_000_000, 'monthly_micro_usd': 10_000_000}
MEASUREMENT = {'median': 'middle pair mean', 'p90': 'nearest-rank ceil(0.9*n)',
               'minimum_p90_samples': 10, 'median_seconds': 20, 'p90_seconds': 30,
               'boundary': 'button to checked result screen; server alone is unknown'}
PAID_CONDITIONS = ('contract', 'frozen_inputs', 'cost_reservation', 'provider_account',
                   'server_secret_storage', 'provider_support_and_terms', 'firebase_iam',
                   'allowed_uid', 'https', 'database', 'deletion_and_backup_retention')


def paid_preflight(stage, conditions):
    missing = [key for key in PAID_CONDITIONS if conditions.get(key) is not True]
    return {'ready': stage == 'before_separate_server' and not missing,
            'stage': stage, 'missing': missing, 'transport_enabled': False,
            'boundary': 'offline readiness only; no paid transport or billing validation'}


def subscription_account(claude, cancelled, timeout=15):
    command = [claude, 'auth', 'status']
    deadline = monotonic() + timeout
    if cancelled.is_set():
        raise ValueError('cancelled')
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=qa.environment())
    raw = b''
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                if cancelled.is_set():
                    raise ValueError('cancelled')
                if monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                if not selector.select(min(.05, max(0, deadline-monotonic()))):
                    continue
                chunk = os.read(child.stdout.fileno(), 65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > 1024 * 1024:
                    raise ValueError('auth output limit')
        account = json.loads(raw)
    finally:
        # Keep the leader unreaped until both signals, as in the role transport.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(child.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
            if sig == signal.SIGTERM:
                threading.Event().wait(.05)
        child.wait()
        child.stdout.close()
    if child.returncode != 0:
        raise ValueError('auth failed')
    return account


def initial(goal, available, remaining, blocker='', unknown=()):
    return {'goal': goal, 'available': available, 'remaining_work': remaining,
            'current_blocker': blocker, 'unknown': list(unknown), 'available_minutes': 5,
            'knowledge': '제공한 사실 외에는 모른다.', 'energy': '앉아서 한 행동을 할 수 있다.',
            'user_request': '목표에 기여하는 첫 행동 하나를 제안한다.',
            'completed_ids': [], 'previous_proposals': [], 'request_kind': 'first_action'}


def launch_flows(regression):
    # Source decisions: #3/#6 and #47's confirmed synthetic starting conditions.
    resume = initial('이력서·포트폴리오·대표 저장소와 페이지를 지원 가능한 상태로 정리한다.',
        ['기존 원고에 경험 A인 iOS 빌드 환경 분리 설명이 있다.',
         '경험 A는 최종 이력서 경험으로 선정된 것은 아니다.',
         '외부 원고에 쓰기 어려우면 이 경험을 참조한 빈 메모에 표시할 수 있다.'],
        ['역할과 기여를 확인하여 문서에 남기기', '근거가 부족한 주장을 구분하기',
         '이력서·포트폴리오 PDF와 대표 저장소·페이지 정리'])
    specs = []
    for name, blocker, meaning in [
        ('ready', '', '기존 원고의 경험 A에서 본인 역할을 구분한 결과 하나를 남긴다.'),
        ('quantity', '한 문장 작성이 부담스럽다.', '역할 선택 표시 같은 실제 수행량 감소를 확인한다.'),
        ('method', '역할을 설명하는 방법을 모른다.', '역할 표현 예시와 채울 부분 하나를 제공한다.'),
        ('evidence', '성과 근거가 부족하다.', '확인할 기록 또는 필요한 기록 종류 하나를 명시한다.'),
        ('selection', '경험 선택이 어렵다.', '경험 A를 후보로 제공한다. 선택을 그대로 되돌리지 않는다.'),
    ]:
        data = deepcopy(resume)
        data['current_blocker'] = blocker
        specs.append(('fixed', name, data, meaning, ['action', 'minimum', 'need_info'], 2))
    fixtures = {c['id']: c['input'] for c in regression['cases'] if 'input' in c}
    books = deepcopy(fixtures['generate-smaller'])
    books.update(request_kind='first_action', previous_proposals=[],
                 user_request='목표에 기여하는 첫 행동 하나를 제안한다.')
    translation = deepcopy(fixtures['generate-next'])
    translation.update(request_kind='first_action', completed_ids=[], previous_proposals=[],
        user_request='목표에 기여하는 첫 행동 하나를 제안한다.',
        available=["자료: 'The window is closed.'와 'The door is open.'", '작성 문서는 비어 있다.'],
        remaining_work=['두 영어 문장을 한국어로 번역하여 문서에 적기'])
    report = initial('분기 업무 보고서 초안 쓰기',
        ['빈 보고서 문서가 열려 있다.', '완료 조건: 목차 3개·성과 3줄·저장.',
         '합성 성과 자료: API 로그인 모의 검사 통과·프로필 편집 UI 초안 완료·배포 절차 초안 작성.'],
        ['목차 3개 작성', '합성 성과 자료로 성과 3줄 작성', '보고서 저장'])
    for name, data, meaning in [
        ('work', report, '제공한 합성 자료로 결과를 남긴다. 수치와 실제 회사 성과를 만들지 않는다.'),
        ('learning', translation, '유용한 번역 결과를 남긴다. 두 문장 이전에 목표를 완료하지 않는다.'),
        ('life', books, '실제 책 이동으로 결과를 남긴다. 축소에서 남은 책을 보존한다.'),
    ]:
        specs.append(('additional', name, data, meaning, ['action', 'minimum', 'need_info'], 2))
    missing = deepcopy(resume)
    missing['available'] = ['경험 A: iOS 빌드 환경 분리라는 제목만 있다. 역할과 원고 내용은 없다.']
    missing['unknown'] = ['본인 역할과 경험 A의 실제 내용']
    role_done = deepcopy(resume)
    role_done.update(request_kind='next_action', completed_ids=['role-mark'],
                     user_request='완료한 역할 표시를 반복하지 않고 다음 행동을 제안한다.')
    role_done['available'].append('이미 완료한 행동: 경험 A의 본인 역할 표시. 구체적인 역할 내용은 미확인이다.')
    role_done['remaining_work'] = ['성과 근거 확인', '문서·저장소·페이지 정리']
    small_done = deepcopy(role_done)
    small_done['available'].append('작은 역할 표시만 완료했다. 원래 문서 정리 목표는 미완료다.')
    for name, data, meaning, statuses in [
        ('missing', missing, '필요한 역할 정보 하나를 확인한다. 없는 사실을 만들지 않는다.', ['need_info']),
        ('role-done', role_done, '완료한 역할 표시를 다시 제안하지 않는다.', ['action', 'minimum', 'need_info']),
        ('small-done', small_done, '작은 행동 완료를 목표 완료로 바꾸지 않는다.', ['action', 'minimum', 'need_info']),
    ]:
        specs.append(('boundary', name, data, meaning, statuses, 0))
    return [dict(id=f'{group}-{name}-{repeat+1}', group=group, input=deepcopy(data),
                 expected={'statuses': statuses[:], 'verdicts': ['accept'], 'meaning': meaning},
                 max_smaller=smaller)
            for group, name, data, meaning, statuses, smaller in specs for repeat in range(3)]


def freeze(directory, *, owner, ends_at, delete_method, role_reservation_micro_usd=20_000,
           monthly_spent_micro_usd=0):
    directory = Path(directory).resolve()
    end = datetime.fromisoformat(ends_at)
    if not owner.strip() or not delete_method.strip() or end.tzinfo is None or end <= datetime.now(timezone.utc):
        raise ValueError('retention owner, future end time and deletion method required')
    if (type(role_reservation_micro_usd) is not int or role_reservation_micro_usd <= 0
            or type(monthly_spent_micro_usd) is not int or monthly_spent_micro_usd < 0):
        raise ValueError('nonnegative integer planning cost required')
    if directory.is_relative_to(qa.REPO.resolve()) and not directory.is_relative_to((qa.REPO/'work').resolve()):
        raise ValueError('raw bundles must be outside tracked source or in ignored work')
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    qa.freeze(directory / 'regression', 'quality', output_mode='text-json')
    regression = qa.load(directory / 'regression')
    sources = deepcopy(regression['sources'])
    for name in ['scripts/launch_evaluation.py', 'services/api/src/development_ai.rs',
                 'services/api/src/user_ai/decision.rs']:
        raw = (qa.REPO / name).read_bytes()
        sources[name] = {'sha256': qa.digest(raw), 'utf8': raw.decode()}
    evidence = {p.relative_to(qa.REPO).as_posix(): qa.digest(p.read_bytes())
                for p in (qa.REPO / 'docs/research/fixtures').glob('*') if p.is_file()}
    manifest = {'version': 1, 'suite': 'launch', 'model': qa.MODEL, 'effort': qa.EFFORT,
        'sources': sources, 'prompts': regression['prompts'], 'schemas': regression['schemas'],
        'flows': launch_flows(regression), 'limits': LIMITS, 'measurement': MEASUREMENT,
        'pipeline_seconds': 120, 'output_mode': 'text-json', 'parallelism': 1,
        'cost_policy': {'role_reservation_micro_usd': role_reservation_micro_usd,
                        'monthly_spent_micro_usd': monthly_spent_micro_usd,
                        'basis': 'offline planning assumption; not provider pricing or billing'},
        'regression': {'cases': 47, 'manifest_sha256': qa.digest((directory/'regression/manifest.json').read_bytes())},
        'preserved_evidence': evidence, 'paid_transport': 'unavailable',
        'retention': {'location': str(directory), 'owner': owner, 'evaluation_ends_at': end.isoformat(),
                      'delete_by': (end + timedelta(days=30)).isoformat(), 'delete_method': delete_method},
        'boundary': 'subscription OAuth QA; paid billing, actual action and device validation unknown'}
    qa.save(directory / 'manifest.json', manifest)
    qa.save(directory / 'integrity.json', {'manifest_sha256': qa.digest((directory/'manifest.json').read_bytes())})


def load(directory):
    manifest = qa.load(Path(directory))
    if manifest.get('suite') != 'launch' or manifest.get('parallelism') != 1:
        raise ValueError('wrong launch manifest')
    if qa.digest(Path(__file__).read_bytes()) != manifest['sources']['scripts/launch_evaluation.py']['sha256']:
        raise ValueError('launch runner differs from frozen version')
    if qa.digest((Path(directory)/'regression/manifest.json').read_bytes()) != manifest['regression']['manifest_sha256']:
        raise ValueError('regression changed')
    return manifest


class Budget:
    def __init__(self, manifest, clock):
        self.limits, self.policy, self.clock = manifest['limits'], manifest['cost_policy'], clock
        self.started = None
        self.requests = self.calls = self.charged = self.conservative = 0

    def admit(self):
        if self.started is not None and self.clock() - self.started >= self.limits['seconds']:
            return 'time_limit'
        if self.requests >= self.limits['requests']:
            return 'request_limit'
        if self.calls + 2 > self.limits['calls']:
            return 'call_limit'
        reserve = self.policy['role_reservation_micro_usd'] * 2
        if self.charged + reserve > self.limits['initial_micro_usd']:
            return 'initial_budget_limit'
        if self.charged + reserve + self.policy['monthly_spent_micro_usd'] > self.limits['monthly_micro_usd']:
            return 'monthly_budget_limit'
        if self.started is None:
            self.started = self.clock()
        self.requests += 1
        return None

    def start_role(self):
        self.calls += 1
        self.charged += self.policy['role_reservation_micro_usd']

    def settle(self, result):
        usage = result.get('usage', {})
        known = all(type(usage.get(key)) in (int, float) and qa.numeric(usage[key]) is not None
                    for key in ('input_tokens', 'output_tokens'))
        cost = result.get('cost_estimate_micro_usd')
        if not known or cost is None:
            self.conservative += 1
            result['cost_state'] = 'conservative_reservation'
            return None if known else 'usage_unknown'
        if type(cost) is not int or cost < 0:
            self.conservative += 1
            result['cost_state'] = 'conservative_reservation'
            return 'invalid_settlement'
        self.charged += cost - self.policy['role_reservation_micro_usd']
        result['cost_state'] = 'estimated'
        return 'cost_overrun' if cost > self.policy['role_reservation_micro_usd'] else None

    def snapshot(self):
        return {'charged_micro_usd': self.charged, 'conservative_roles': self.conservative,
                'monthly_spent_micro_usd': self.policy['monthly_spent_micro_usd'],
                'basis': self.policy['basis'], 'actual_billing': None}


def metrics(values, measurement):
    values = sorted(values)
    median = statistics.median(values) if values else None
    p90 = values[math.ceil(.9 * len(values)) - 1] if len(values) >= measurement['minimum_p90_samples'] else None
    return {'samples': len(values), 'median': median, 'p90': p90,
            'sla_passed': None if p90 is None else median <= measurement['median_seconds']
                                                  and p90 <= measurement['p90_seconds']}


def report(directory, *, observations=()):
    directory = Path(directory)
    manifest = load(directory)
    claim = json.loads((directory/'run-started.json').read_bytes())
    if not (directory/'run-ended.json').exists():
        birth = qa.process_birth(claim['controller_pid'])
        if birth and birth == claim['controller_birth']:
            raise ValueError('controller still alive; do not report an active run')
    records, unreadable = [], []
    for path in sorted((directory/'results').glob('*.json')):
        try:
            row = json.loads(path.read_bytes())
            if type(row) is not dict or any(type(row.get(key)) is not str
                    for key in ('run_id', 'manifest_sha256', 'request_id', 'flow', 'request_kind')):
                raise ValueError('invalid result identity')
            if qa.numeric(row.get('seconds')) is None or type(row.get('calls')) is not list:
                raise ValueError('invalid result structure')
            if row['flow'] not in {f['id'] for f in manifest['flows']} or row['request_kind'] not in ('first_action', 'smaller', 'next_action'):
                raise ValueError('unrelated result flow')
            if any(key in row and type(row[key]) is not str for key in ('error', 'verdict', 'termination')):
                raise ValueError('invalid result outcome')
            for call in row['calls']:
                if type(call) is not dict or call.get('role') not in ('generate', 'check'):
                    raise ValueError('invalid role record')
                if type(call.get('provider_messages', 0)) is not int or call.get('provider_messages', 0) < 0:
                    raise ValueError('invalid role message count')
                usage = call.get('usage', {})
                if type(usage) is not dict or any(v is not None and qa.numeric(v) is None for v in usage.values()):
                    raise ValueError('invalid role usage')
                if ('error' in call and type(call['error']) is not str
                        or 'output' in call and type(call['output']) is not dict):
                    raise ValueError('invalid role outcome')
            if row['run_id'] != claim['run_id'] or row['manifest_sha256'] != claim['manifest_sha256']:
                raise ValueError('unrelated result')
            records.append(row)
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            unreadable.append(path.name)
    ids = [r['request_id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate result identity')
    screens = {}
    for item in observations:
        ident = item['request_id']
        if ident not in ids or ident in screens or item.get('run_id') != claim['run_id']:
            raise ValueError('unrelated or duplicate screen observation')
        seconds = qa.numeric(item.get('observed_upper_seconds'))
        interval = qa.numeric(item.get('sample_interval_seconds'))
        evidence = item.get('evidence_sha256', '')
        if (seconds is None or interval is None or not item.get('method', '').strip()
                or item.get('display_observed') is not True or len(evidence) != 64
                or any(c not in '0123456789abcdef' for c in evidence)):
            raise ValueError('screen observation method and upper bound required')
        try:
            path = Path(item['evidence_path'])
            if path.is_absolute() or '..' in path.parts or not path.parts:
                raise ValueError('evidence path must stay inside private bundle')
            digest = hashlib.sha256()
            with ExitStack() as opened:
                if '..' in directory.parts:
                    raise ValueError('bundle path must not contain parent traversal')
                parent = os.open(directory.anchor or '.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                opened.callback(os.close, parent)
                bundle_parts = directory.parts[1:] if directory.is_absolute() else directory.parts
                for part in bundle_parts:
                    parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    opened.callback(os.close, parent)
                for part in path.parts[:-1]:
                    parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    opened.callback(os.close, parent)
                descriptor = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                opened.callback(os.close, descriptor)
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValueError('screen evidence must be a regular file')
                source = opened.enter_context(os.fdopen(descriptor, 'rb', closefd=False))
                for chunk in iter(lambda: source.read(65536), b''):
                    digest.update(chunk)
            if digest.hexdigest() != evidence:
                raise ValueError('screen evidence mismatch')
        except (OSError, KeyError, TypeError, ValueError):
            raise ValueError('private screen evidence missing or mismatched') from None
        screens[ident] = seconds
    calls = [c for r in records for c in r['calls']]
    normal = [r for r in records if r.get('verdict') == 'accept' and r.get('reference_matched') and not r.get('error')]
    timings = {}
    for kind in ('first_action', 'smaller', 'other'):
        timings[kind] = metrics([screens[r['request_id']] for r in normal
            if (r['request_kind'] if r['request_kind'] in {'first_action', 'smaller'} else 'other') == kind
            and r['request_id'] in screens], manifest['measurement'])
    completed = {r['flow'] for r in records if r.get('termination') and not r.get('error')}
    end = json.loads((directory/'run-ended.json').read_bytes()) if (directory/'run-ended.json').exists() else {}
    started_requests = len(list((directory/'requests').glob('*.json')))
    started_roles = len(list((directory/'calls').glob('*.json')))
    errors = Counter(r['error'] for r in records if r.get('error'))
    for row in records:
        row['outcome'] = ('cancelled' if row.get('error') in {'cancelled', 'ownership_lost'} else
                          'timed_out' if row.get('error') == 'timed_out' else
                          row['verdict'] if row.get('verdict') in {'reject', 'uncertain'} else
                          'failed' if row.get('error') else row.get('verdict', 'failed'))
    outcomes = Counter(r['outcome'] for r in records)
    condition_timings = {condition: {kind: metrics([screens[r['request_id']] for r in normal
        if r['flow'].rsplit('-', 1)[0] == condition and r['request_kind'] == kind and r['request_id'] in screens],
        manifest['measurement']) for kind in ('first_action', 'smaller', 'next_action')}
        for condition in sorted({f['id'].rsplit('-', 1)[0] for f in manifest['flows']})}
    return {'run_id': claim['run_id'], 'manifest_sha256': claim['manifest_sha256'],
        'scheduled_flows': len(manifest['flows']), 'completed_flows': len(completed),
        'unexecuted_flows': [f['id'] for f in manifest['flows'] if f['id'] not in completed],
        'requests': {'started': started_requests, 'recorded': len(records),
                     'unrecorded': started_requests - len(records),
                     'completed': sum('verdict' in r for r in records),
                     'failed': sum(bool(r.get('error')) for r in records)},
        'roles': {'started': started_roles, 'unrecorded': started_roles - len(calls),
                  'completed': sum('output' in c and not c.get('error') for c in calls),
                  'failed': sum(bool(c.get('error')) and c['error'] not in {'cancelled', 'timed_out'} for c in calls),
                  'cancelled': sum(c.get('error') == 'cancelled' for c in calls),
                  'timed_out': sum(c.get('error') == 'timed_out' for c in calls),
                  'model_messages': sum(c.get('provider_messages', 0) for c in calls)},
        'terminations': dict(Counter(r['termination'] for r in records if r.get('termination'))),
        'outcomes': dict(outcomes), 'errors': dict(errors), 'unreadable_records': unreadable,
        'reference_mismatches': sum(r.get('reference_matched') is False for r in records),
        'structure_passed': sum(r.get('structure_valid') is True for r in records),
        'semantic_criteria': [1, 2, 3, 4, 5], 'human_review': 'not_performed', 'quality_passed': None,
        'timings': timings, 'condition_timings': condition_timings,
        'screen_missing': sum(r['request_id'] not in screens for r in normal),
        'server_timings': {kind: dict(metrics([r['seconds'] for r in normal if r['request_kind'] == kind],
                                    manifest['measurement']), sla_passed=None)
                           for kind in ('first_action', 'smaller')},
        'outcome_seconds': {kind: [r['seconds'] for r in records if r['outcome'] == kind]
                           for kind in ('accept', 'reject', 'uncertain', 'failed', 'cancelled', 'timed_out')},
        'stop_reason': end.get('reason', 'interrupted'),
        'automatic_passed': len(completed) == len(manifest['flows']) and not errors and not unreadable
                            and started_roles == len(calls) and started_requests == len(records)
                            and all(r.get('reference_matched') is True for r in records),
        'costs': end.get('budget', {'actual_billing': None,
            'charged_micro_usd': started_roles * manifest['cost_policy']['role_reservation_micro_usd'],
            'conservative_roles': started_roles, 'basis': 'interrupted run conservative reservation'}),
        'role_usage': {role: {key: {'known_total': sum(c.get('usage', {}).get(key) or 0
                               for c in calls if c['role'] == role),
                                  'unknown_calls': sum(c.get('usage', {}).get(key) is None
                               for c in calls if c['role'] == role)}
                         for key in ('input_tokens', 'output_tokens', 'thinking_tokens',
                                     'cache_read_input_tokens', 'cache_creation_input_tokens')}
                       for role in ('generate', 'check')},
        'paid_budget_verified': False, 'model': manifest['model'], 'requested_effort': manifest['effort']}


def run(directory, *, claude='claude', invoke=None, cancelled=None, clock=monotonic, lock_path=None,
        mode='subscription'):
    if mode != 'subscription':
        raise ValueError('paid transport unavailable; separate-server preconditions required')
    directory = Path(directory)
    manifest = load(directory)
    if datetime.now(timezone.utc) >= datetime.fromisoformat(manifest['retention']['evaluation_ends_at']):
        raise ValueError('frozen evaluation end time reached')
    lock_path = Path(lock_path or qa.REPO/'work/launch-model.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    cancelled = cancelled or threading.Event()
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another launch evaluation owns the model') from None
        claim = {'run_id': uuid.uuid4().hex, 'manifest_sha256': qa.digest((directory/'manifest.json').read_bytes()),
                 'controller_pid': os.getpid(), 'controller_birth': qa.process_birth(os.getpid())}
        qa.save(directory/'run-started.json', claim)
        for name in ('results', 'requests', 'calls'):
            (directory/name).mkdir(mode=0o700)
        done, lost = threading.Event(), threading.Event()
        claim_hash = qa.digest((directory/'run-started.json').read_bytes())

        def owned():
            try:
                return (os.fstat(lock.fileno()).st_ino == lock_path.stat().st_ino
                        and claim_hash == qa.digest((directory/'run-started.json').read_bytes()))
            except OSError:
                return False

        def monitor():
            while not done.wait(.05):
                if not owned():
                    lost.set()
                    cancelled.set()

        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        previous = {}
        if threading.current_thread() is threading.main_thread():
            previous = {sig: signal.signal(sig, lambda *_: cancelled.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
        reason = 'completed'
        budget = Budget(manifest, clock)
        try:
            if invoke is None:
                account = subscription_account(claude, cancelled)
                if not (account.get('loggedIn') is True and account.get('authMethod') == 'claude.ai'
                        and account.get('apiProvider') == 'firstParty'):
                    raise ValueError('subscription OAuth login required')
                invoke = lambda role, prompt, schema, data, deadline, cancel: qa.call(
                    claude, prompt, schema, data, deadline, cancel, output_mode=manifest['output_mode'])
            for flow in manifest['flows']:
                data = deepcopy(flow['input'])
                for step in range(flow['max_smaller'] + 1):
                    if not owned() or lost.is_set():
                        reason = 'ownership_lost'
                        cancelled.set()
                        break
                    if cancelled.is_set():
                        reason = 'cancelled'
                        break
                    limit = budget.admit()
                    if limit:
                        reason = limit
                        break
                    started = clock()
                    deadline = min(started + manifest['pipeline_seconds'], budget.started + manifest['limits']['seconds'])
                    ident = f"{claim['run_id']}-{flow['id']}-{step}"
                    row = dict(run_id=claim['run_id'], manifest_sha256=claim['manifest_sha256'],
                               request_id=ident, flow=flow['id'], step=step, request_kind=data['request_kind'], calls=[])
                    qa.save(directory/'requests'/f'{ident}.json', dict(row, input_sha256=qa.digest(qa.encoded(data))))
                    candidate = None
                    try:
                        for role in ('generate', 'check'):
                            if cancelled.is_set() or not owned() or clock() >= deadline:
                                row['error'] = ('ownership_lost' if not owned() else
                                                'cancelled' if cancelled.is_set() else 'timed_out')
                                break
                            schema = qa.schema_for(manifest, data) if role == 'generate' else manifest['schemas']['check']
                            sent = deepcopy(data) if role == 'generate' else {'original_request': deepcopy(data), 'candidate': candidate}
                            budget.start_role()
                            qa.save(directory/'calls'/f'{ident}-{role}.json',
                                    {'request_id': ident, 'role': role, 'run_id': claim['run_id']})
                            row['calls'].append({'role': role, 'requested_effort': manifest['effort'],
                                                 'error': 'runner_failed'})
                            result = invoke(role, manifest['prompts'][role], schema, sent, deadline, cancelled)
                            row['calls'][-1].pop('error')
                            row['calls'][-1].update(result)
                            settlement = budget.settle(row['calls'][-1])
                            if result.get('error'):
                                row['error'] = result['error']
                                break
                            if settlement or clock() >= deadline:
                                row['error'] = settlement or 'timed_out'
                                break
                            if result.get('actual_models') != [manifest['model']] or result.get('provider_messages') != 1:
                                row['error'] = 'model_or_call_count'
                                break
                            if result.get('provider_retries', 0) or result.get('additional_provider_requests', 0):
                                row['error'] = 'unexpected_retry'
                                break
                            if result.get('cli_pid') and (not result.get('process_reaped') or result.get('process_group_alive')):
                                row['error'] = 'process_cleanup'
                                break
                            output = result.get('output')
                            qa.validate(output, schema)
                            if role == 'generate':
                                if not qa.proposal_valid(data, output):
                                    row['error'] = 'invalid_proposal'
                                    break
                                candidate = output
                                row['structure_valid'] = True
                            else:
                                if not qa.check_valid(output):
                                    row['error'] = 'invalid_check'
                                    break
                                row.update(verdict=output['verdict'], criteria=output['criteria'], status=candidate['status'])
                                row['reference_matched'] = (output['verdict'] in flow['expected']['verdicts']
                                    and candidate['status'] in flow['expected']['statuses'])
                                if not row['reference_matched']:
                                    row['error'] = 'unexpected_quality'
                                elif output['verdict'] != 'accept':
                                    row['termination'] = 'expected_' + output['verdict']
                                elif candidate['status'] in {'need_info', 'minimum', 'no_action'}:
                                    row['termination'] = candidate['status']
                                elif step == flow['max_smaller']:
                                    row['termination'] = 'planned_limit'
                    except qa.OutputError as error:
                        row['error'] = 'invalid_output'
                        row['output_error'] = error.detail
                    except Exception:
                        row['error'] = 'runner_failed'
                        if row['calls'] and row['calls'][-1].get('error') == 'runner_failed':
                            budget.settle(row['calls'][-1])
                    row['seconds'] = clock() - started
                    if cancelled.is_set() or not owned():
                        row['error'] = 'ownership_lost' if lost.is_set() or not owned() else 'cancelled'
                    qa.save(directory/'results'/f'{len(list((directory/"results").glob("*.json"))):03d}.json', row)
                    if row.get('error'):
                        reason = ('time_limit' if row['error'] == 'timed_out'
                                  and clock() - budget.started >= manifest['limits']['seconds'] else row['error'])
                        break
                    if row.get('termination'):
                        break
                    data['previous_proposals'].append(deepcopy(candidate))
                    data['request_kind'] = 'smaller'
                    data['user_request'] = '현재 행동을 실질적으로 줄인다. 반복 막힘이면 첫 막힘 한 가지를 확인한다.'
                if reason != 'completed':
                    break
        except Exception:
            reason = 'ownership_lost' if lost.is_set() else 'cancelled' if cancelled.is_set() else 'runner_failed'
        finally:
            done.set()
            watcher.join()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            ended = datetime.now(timezone.utc)
            qa.save(directory/'run-ended.json', {'reason': reason, 'budget': budget.snapshot(),
                'ended_at': ended.isoformat(), 'delete_by': min(ended + timedelta(days=30),
                        datetime.fromisoformat(manifest['retention']['delete_by'])).isoformat()})
        summary = report(directory)
        qa.save(directory/'summary.json', summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    frozen = commands.add_parser('freeze')
    frozen.add_argument('directory', type=Path)
    frozen.add_argument('--owner', required=True)
    frozen.add_argument('--ends-at', required=True, help='timezone-qualified evaluation cutoff')
    frozen.add_argument('--delete-method', required=True)
    frozen.add_argument('--role-reservation-micro-usd', type=int, required=True,
                        help='offline planning assumption; not actual pricing or billing')
    frozen.add_argument('--monthly-spent-micro-usd', type=int, required=True)
    running = commands.add_parser('run')
    running.add_argument('directory', type=Path)
    running.add_argument('--claude', default='claude')
    reporting = commands.add_parser('report')
    reporting.add_argument('directory', type=Path)
    reporting.add_argument('--observations', type=Path)
    reporting.add_argument('--output', default='report.json')
    preflight = commands.add_parser('paid-preflight')
    preflight.add_argument('--stage', choices=('preparation', 'before_separate_server'), required=True)
    preflight.add_argument('--conditions', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'freeze':
            freeze(args.directory, owner=args.owner, ends_at=args.ends_at, delete_method=args.delete_method,
                   role_reservation_micro_usd=args.role_reservation_micro_usd,
                   monthly_spent_micro_usd=args.monthly_spent_micro_usd)
            print(json.dumps({'frozen': True, 'model_calls': 0}))
            return 0
        if args.command == 'run':
            summary = run(args.directory, claude=args.claude)
        elif args.command == 'report':
            if Path(args.output).name != args.output or args.output in {'manifest.json', 'integrity.json'}:
                raise ValueError('report filename required')
            observations = json.loads(args.observations.read_bytes()) if args.observations else []
            summary = report(args.directory, observations=observations)
            qa.save(args.directory/args.output, summary)
        else:
            summary = paid_preflight(args.stage, json.loads(args.conditions.read_bytes()))
            print(json.dumps(summary))
            return 0 if summary['ready'] else 1
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary['automatic_passed'] else 1
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        # Paths, provider exceptions and input values belong only in the private bundle.
        print(json.dumps({'error': 'launch_evaluation_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

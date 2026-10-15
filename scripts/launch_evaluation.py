#!/usr/bin/env python3
"""Opt-in, sequential launch QA. Paid transport is deliberately unavailable."""
import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
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
# Two 4 MiB role streams plus record metadata and JSON encoding overhead.
REPORT_JSON_LIMIT = 16 * 1024 * 1024
MARKER_JSON_LIMIT = 4096
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


def private_root(repo=qa.REPO):
    # Raw bundles must outlive worktrees; #115's bundle was lost with a removed worktree.
    # GIT_* variables (e.g. inside another repository's hook) must not redirect the root.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    common = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                            cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()
    return (Path(common).parent / 'work').resolve()


def freeze(directory, *, owner, ends_at, delete_method, role_reservation_micro_usd=20_000,
           monthly_spent_micro_usd=0, flow=None, max_smaller=None):
    directory = Path(directory).resolve()
    end = datetime.fromisoformat(ends_at)
    if not owner.strip() or not delete_method.strip() or end.tzinfo is None or end <= datetime.now(timezone.utc):
        raise ValueError('retention owner, future end time and deletion method required')
    if (type(role_reservation_micro_usd) is not int or role_reservation_micro_usd <= 0
            or type(monthly_spent_micro_usd) is not int or monthly_spent_micro_usd < 0):
        raise ValueError('nonnegative integer planning cost required')
    if (flow is None) != (max_smaller is None) or max_smaller is not None and (
            type(max_smaller) is not int or max_smaller < 0):
        raise ValueError('a single flow needs a nonnegative smaller count')
    root = private_root()
    if directory == root or not directory.is_relative_to(root):
        raise ValueError(f'raw bundles must be inside the main checkout work directory: {root}')
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    qa.freeze(directory / 'regression', 'quality', output_mode='text-json', sequential=True)
    regression = qa.load(directory / 'regression')
    sources = deepcopy(regression['sources'])
    for name in ['scripts/launch_evaluation.py', 'services/api/src/suggestion.rs',
                 'services/api/src/suggestion/compact.rs']:
        raw = (qa.REPO / name).read_bytes()
        sources[name] = {'sha256': qa.digest(raw), 'utf8': raw.decode()}
    flows, limits = launch_flows(regression), LIMITS
    if flow is not None:
        # #154: one fixed flow, with request and role caps derived from its planned steps.
        flows = [f for f in flows if f['id'] == flow]
        if len(flows) != 1 or max_smaller > flows[0]['max_smaller']:
            raise ValueError('known flow and a smaller count within its plan required')
        flows[0]['max_smaller'] = max_smaller
        limits = dict(LIMITS, requests=max_smaller + 1, calls=2 * (max_smaller + 1))
    evidence = {p.relative_to(qa.REPO).as_posix(): qa.digest(p.read_bytes())
                for p in (qa.REPO / 'docs/research/fixtures').glob('*') if p.is_file()}
    manifest = {'version': 1, 'suite': 'launch', 'model': qa.MODEL, 'effort': qa.EFFORT,
        'sources': sources, 'prompts': regression['prompts'], 'schemas': regression['schemas'],
        'flows': flows, 'limits': limits, 'measurement': MEASUREMENT,
        'pipeline_seconds': 120, 'output_mode': 'text-json', 'parallelism': 1,
        'cost_policy': {'role_reservation_micro_usd': role_reservation_micro_usd,
                        'monthly_spent_micro_usd': monthly_spent_micro_usd,
                        'basis': 'offline planning assumption; not provider pricing or billing'},
        'regression': {'cases': 47, 'manifest_sha256': qa.digest(private_bytes(directory, 'regression/manifest.json'))},
        'preserved_evidence': evidence, 'paid_transport': 'unavailable',
        'retention': {'location': str(directory), 'owner': owner, 'evaluation_ends_at': end.isoformat(),
                      'delete_by': (end + timedelta(days=30)).isoformat(), 'delete_method': delete_method},
        'boundary': 'subscription OAuth QA; paid billing, actual action and device validation unknown'}
    qa.save(directory / 'manifest.json', manifest)
    qa.save(directory / 'integrity.json', {'manifest_sha256': qa.digest(private_bytes(directory, 'manifest.json'))})


def load(directory, *, descriptor=None):
    directory = Path(directory)
    source = directory if descriptor is None else descriptor
    manifest = qa.load(directory, read_bytes=lambda path: private_bytes(source, path.relative_to(directory)))
    if manifest.get('suite') != 'launch' or manifest.get('parallelism') != 1:
        raise ValueError('wrong launch manifest')
    if qa.digest(Path(__file__).read_bytes()) != manifest['sources']['scripts/launch_evaluation.py']['sha256']:
        raise ValueError('launch runner differs from frozen version')
    if qa.digest(private_bytes(source, 'regression/manifest.json')) != manifest['regression']['manifest_sha256']:
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
    lower = statistics.median_low(values) if values else None
    median = lower + (statistics.median_high(values) - lower) / 2 if values else None
    p90 = values[math.ceil(.9 * len(values)) - 1] if len(values) >= measurement['minimum_p90_samples'] else None
    return {'samples': len(values), 'median': median, 'p90': p90,
            'sla_passed': None if p90 is None else median <= measurement['median_seconds']
                                                  and p90 <= measurement['p90_seconds']}


@contextmanager
def private_directory(directory, path='.'):
    path = Path(path)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('private path must stay inside bundle')
    with ExitStack() as opened:
        if type(directory) is int:
            parent, bundle_parts = os.dup(directory), ()
        else:
            directory = Path(directory)
            if '..' in directory.parts:
                raise ValueError('private path must stay inside bundle')
            parent = os.open(directory.anchor or '.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            bundle_parts = directory.parts[1:] if directory.is_absolute() else directory.parts
        opened.callback(os.close, parent)
        for part in bundle_parts + path.parts:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            opened.callback(os.close, parent)
        yield parent


@contextmanager
def private_source(directory, path):
    path = Path(path)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('private path must stay inside bundle')
    with ExitStack() as opened:
        if type(directory) is dict:
            source = directory.get(str(path))
            if source is None or type(source) is bytes:
                raise ValueError('private snapshot source unavailable')
            if type(source) is tuple:
                source = source[0]
            copied = opened.enter_context(os.fdopen(os.dup(source.fileno()), 'rb'))
            copied.seek(0)
            yield copied
            return
        with private_directory(directory, path.parent) as parent:
            descriptor = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            opened.callback(os.close, descriptor)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('private source must be a regular file')
        yield opened.enter_context(os.fdopen(descriptor, 'rb', closefd=False))


def private_bytes(directory, path, *, limit=REPORT_JSON_LIMIT, expected_identity=None):
    if type(directory) is dict and type(directory.get(str(Path(path)))) is bytes:
        data = directory[str(Path(path))]
        if len(data) > limit:
            raise ValueError('private snapshot JSON too large')
        return data
    try:
        with private_source(directory, path) as source:
            current = os.fstat(source.fileno())
            if expected_identity is not None and (current.st_dev, current.st_ino) != expected_identity:
                raise ValueError('private source changed after enumeration')
            if current.st_size > limit:
                raise ValueError('report JSON too large')
            data = source.read(limit + 1)
            if len(data) > limit:
                raise ValueError('report JSON grew beyond limit')
            if type(directory) is dict and type(directory.get(str(Path(path)))) is tuple:
                if qa.digest(data) != directory[str(Path(path))][1]:
                    raise ValueError('private snapshot bytes changed')
    except OSError:
        raise ValueError('private report JSON unavailable') from None
    return data


def private_json(directory, path, *, expected_type=dict):
    value = json.loads(private_bytes(directory, path))
    if type(value) is not expected_type:
        raise ValueError('private JSON type invalid')
    return value


def private_names(directory, path):
    if type(directory) is dict:
        return [Path(name).name for name in directory
                if Path(name).parent == Path(path) and name.endswith('.json')]
    with private_directory(directory, path) as descriptor:
        return [name for name in os.listdir(descriptor) if name.endswith('.json')]


def private_exists(directory, path):
    if type(directory) is dict:
        return str(Path(path)) in directory
    try:
        os.stat(path, dir_fd=directory)
        return True
    except FileNotFoundError:
        return False


def report(directory, *, observations=()):
    try:
        with ExitStack() as opened:
            descriptor = opened.enter_context(private_directory(directory))
            snapshot = {}
            for name in ('results', 'requests', 'calls'):
                child = opened.enter_context(private_directory(descriptor, name))
                with os.scandir(child) as entries:
                    identities = [(entry.name, entry.inode()) for entry in entries
                                  if entry.name.endswith('.json') or name in ('requests', 'calls') and entry.name.endswith('.receipt')]
                for filename, inode in identities:
                    source = None
                    try:
                        if name == 'results':
                            source = opened.enter_context(private_source(child, filename))
                            current = os.fstat(source.fileno())
                            if current.st_ino != inode or current.st_dev != os.fstat(child).st_dev:
                                raise ValueError('result changed after enumeration')
                            if current.st_size > REPORT_JSON_LIMIT:
                                raise ValueError('result too large')
                            captured = source.read(REPORT_JSON_LIMIT + 1)
                            if len(captured) > REPORT_JSON_LIMIT:
                                raise ValueError('result grew beyond limit')
                            source = (source, qa.digest(captured))
                        else:
                            source = private_bytes(child, filename, limit=MARKER_JSON_LIMIT,
                                expected_identity=(os.fstat(child).st_dev, inode))
                    except (OSError, ValueError):
                        source = None
                    snapshot[str(Path(name)/filename)] = source
            for name in ('manifest.json', 'integrity.json', 'regression/manifest.json',
                         'run-started.json', 'run-ended.json'):
                if name != 'run-ended.json' or private_exists(descriptor, name):
                    snapshot[name] = opened.enter_context(private_source(descriptor, name))
            for item in observations:
                try:
                    name = str(Path(item['evidence_path']))
                    if name not in snapshot:
                        snapshot[name] = opened.enter_context(private_source(descriptor, name))
                except (OSError, KeyError, TypeError, ValueError):
                    raise ValueError('private screen evidence unavailable') from None
            return report_bundle(Path(directory), snapshot, observations)
    except OSError:
        raise ValueError('private report bundle unavailable') from None


def report_bundle(directory, descriptor, observations):
    directory = Path(directory)
    manifest = load(directory, descriptor=descriptor)
    claim = private_json(descriptor, 'run-started.json')
    if claim.get('manifest_sha256') != qa.digest(private_bytes(descriptor, 'manifest.json')):
        raise ValueError('run manifest binding mismatch')
    if not private_exists(descriptor, 'run-ended.json'):
        birth = qa.process_birth(claim['controller_pid'])
        if birth and birth == claim['controller_birth']:
            raise ValueError('controller still alive; do not report an active run')
    records, unreadable, usage_totals = [], [], Counter()
    flows = {flow['id']: flow for flow in manifest['flows']}
    states = {key: deepcopy(flow['input']) for key, flow in flows.items()}
    steps = Counter()
    seen = set()
    for path in map(Path, sorted(private_names(descriptor, 'results'))):
        try:
            row = private_json(descriptor, Path('results')/path.name)
            if type(row) is not dict or any(type(row.get(key)) is not str
                    for key in ('run_id', 'manifest_sha256', 'request_id', 'flow', 'request_kind', 'result_file')):
                raise ValueError('invalid result identity')
            if row['result_file'] != path.name:
                raise ValueError('noncanonical result file')
            if row['request_id'] in seen:
                raise ValueError('duplicate result identity')
            if qa.numeric(row.get('seconds')) is None or type(row.get('calls')) is not list:
                raise ValueError('invalid result structure')
            if row['flow'] not in {f['id'] for f in manifest['flows']} or row['request_kind'] not in ('first_action', 'smaller', 'next_action'):
                raise ValueError('unrelated result flow')
            if any(key in row and type(row[key]) is not str for key in ('error', 'verdict', 'termination')):
                raise ValueError('invalid result outcome')
            data = states[row['flow']]
            ident = f"{claim['run_id']}-{row['flow']}-{steps[row['flow']]}"
            if (row['request_id'] != ident or row.get('step') != steps[row['flow']]
                    or row['request_kind'] != data['request_kind']):
                raise ValueError('request identity or sequence mismatch')
            request = private_json(descriptor, f'requests/{ident}.json')
            if (any(request.get(key) != row[key] for key in
                    ('run_id', 'manifest_sha256', 'request_id', 'flow', 'step', 'request_kind', 'result_file'))
                    or request.get('input_sha256') != qa.digest(qa.encoded(data))):
                raise ValueError('frozen request mismatch')
            receipt = private_json(descriptor, f'requests/{ident}.receipt')
            if (any(receipt.get(key) != row[key] for key in
                    ('run_id', 'manifest_sha256', 'request_id', 'result_file'))
                    or receipt.get('record_sha256') != qa.digest(qa.encoded(row))):
                raise ValueError('result completion receipt mismatch')
            pending_usage = usage_totals.copy()
            for index, call in enumerate(row['calls']):
                if type(call) is not dict or call.get('role') not in ('generate', 'check'):
                    raise ValueError('invalid role record')
                if type(call.get('provider_messages', 0)) is not int or call.get('provider_messages', 0) < 0:
                    raise ValueError('invalid role message count')
                usage = call.get('usage', {})
                if type(usage) is not dict or any(v is not None and qa.numeric(v) is None for v in usage.values()):
                    raise ValueError('invalid role usage')
                for key, value in usage.items():
                    pending_usage[call['role'], key] += value or 0
                    if not math.isfinite(pending_usage[call['role'], key]):
                        raise ValueError('role usage aggregation overflow')
                if ('error' in call and type(call['error']) is not str
                        or 'output' in call and type(call['output']) is not dict):
                    raise ValueError('invalid role outcome')
                if index >= 2 or call['role'] != ('generate', 'check')[index]:
                    raise ValueError('role sequence mismatch')
                sent = data if index == 0 else {'original_request': data, 'candidate': row['calls'][0].get('output')}
                binding = dict(run_id=claim['run_id'], request_id=ident, role=call['role'],
                    input_sha256=qa.digest(qa.encoded(sent)), manifest_sha256=claim['manifest_sha256'])
                marker = private_json(descriptor, f"calls/{ident}-{call['role']}.json")
                if any(call.get(key) != value or marker.get(key) != value for key, value in binding.items()):
                    raise ValueError('role request binding mismatch')
                receipt_name = f"calls/{ident}-{call['role']}.receipt"
                if private_exists(descriptor, receipt_name):
                    receipt = private_json(descriptor, receipt_name)
                    if (any(receipt.get(key) != value for key, value in binding.items())
                            or receipt.get('record_sha256') != qa.digest(qa.encoded(call))):
                        raise ValueError('role receipt mismatch')
                elif not call.get('error'):
                    raise ValueError('completed role receipt missing')
            if 'verdict' in row:
                flow = flows[row['flow']]
                if [call['role'] for call in row['calls']] != ['generate', 'check']:
                    raise ValueError('decision roles missing')
                candidate, checked = [call['output'] for call in row['calls']]
                qa.validate(candidate, qa.schema_for(manifest, row))
                qa.validate(checked, manifest['schemas']['check'])
                if any(call.get('actual_models') != [manifest['model']]
                       or call.get('provider_messages') != 1 or call.get('provider_retries', 0)
                       or call.get('additional_provider_requests', 0)
                       or any(type(call['usage'].get(key)) not in (int, float)
                              or qa.numeric(call['usage'][key]) is None
                              for key in ('input_tokens', 'output_tokens'))
                       or call.get('cli_pid') and (not call.get('process_reaped') or call.get('process_group_alive'))
                       for call in row['calls']):
                    raise ValueError('inconsistent successful role')
                matched = (checked['verdict'] in flow['expected']['verdicts']
                           and candidate['status'] in flow['expected']['statuses'])
                if (not qa.proposal_valid(flow['input'], candidate) or not qa.check_valid(checked)
                        or row['verdict'] != checked['verdict']
                        or row.get('criteria') != checked['criteria'] or row.get('status') != candidate['status']
                        or row.get('reference_matched') is not matched or row.get('structure_valid') is not True
                        or type(row.get('step')) is not int or not 0 <= row['step'] <= flow['max_smaller']
                        or any(call.get('error') for call in row['calls'])):
                    raise ValueError('inconsistent decision record')
                termination = (None if not matched else 'expected_' + checked['verdict']
                    if checked['verdict'] != 'accept' else candidate['status']
                    if candidate['status'] in {'need_info', 'minimum', 'no_action'} else
                    'planned_limit' if row['step'] == flow['max_smaller'] else None)
                if row.get('termination') != termination:
                    raise ValueError('inconsistent termination')
            elif not row.get('error'):
                raise ValueError('decision or failure required')
            if row['run_id'] != claim['run_id'] or row['manifest_sha256'] != claim['manifest_sha256']:
                raise ValueError('unrelated result')
            records.append(row)
            seen.add(row['request_id'])
            usage_totals = pending_usage
            if not row.get('error') and not row.get('termination'):
                states[row['flow']]['previous_proposals'].append(deepcopy(row['calls'][0]['output']))
                states[row['flow']]['request_kind'] = 'smaller'
                states[row['flow']]['user_request'] = '현재 행동을 실질적으로 줄인다. 반복 막힘이면 첫 막힘 한 가지를 확인한다.'
                steps[row['flow']] += 1
        except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
            unreadable.append(path.name)
    ids = [r['request_id'] for r in records]
    screens = {}
    for item in observations:
        ident = item['request_id']
        if ident not in ids or ident in screens or item.get('run_id') != claim['run_id']:
            raise ValueError('unrelated or duplicate screen observation')
        seconds = qa.numeric(item.get('observed_upper_seconds'))
        interval = qa.numeric(item.get('sample_interval_seconds'))
        evidence = item.get('evidence_sha256', '')
        method = item.get('method')
        if (seconds is None or interval is None or type(method) is not str or not method.strip()
                or item.get('display_observed') is not True or len(evidence) != 64
                or any(c not in '0123456789abcdef' for c in evidence)):
            raise ValueError('screen observation method and upper bound required')
        try:
            path = Path(item['evidence_path'])
            digest = hashlib.sha256()
            with private_source(descriptor, path) as source:
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
    end = private_json(descriptor, 'run-ended.json') if private_exists(descriptor, 'run-ended.json') else {}
    request_names = private_names(descriptor, 'requests')
    started = {flow for flow in flows if f"{claim['run_id']}-{flow}-0.json" in request_names}
    started_requests = len(request_names)
    started_roles = len(private_names(descriptor, 'calls'))
    if private_exists(descriptor, 'run-ended.json'):
        budget = end.get('budget')
        if (type(end.get('reason')) is not str or not end['reason'] or type(budget) is not dict
                or any(type(budget.get(key)) is not int or budget[key] < 0
                       for key in ('charged_micro_usd', 'conservative_roles', 'monthly_spent_micro_usd'))
                or budget['conservative_roles'] > started_roles
                or budget['monthly_spent_micro_usd'] != manifest['cost_policy']['monthly_spent_micro_usd']
                or budget.get('basis') != manifest['cost_policy']['basis']
                or 'actual_billing' not in budget or budget['actual_billing'] is not None):
            raise ValueError('invalid end budget')
        if end['reason'] == 'completed' and (
                budget['charged_micro_usd'] > manifest['limits']['initial_micro_usd']
                or budget['charged_micro_usd'] + budget['monthly_spent_micro_usd'] > manifest['limits']['monthly_micro_usd']
                or started_requests > manifest['limits']['requests'] or started_roles > manifest['limits']['calls']):
            raise ValueError('completed execution exceeds limits')
        if (end['reason'] == 'completed' and not unreadable and started_roles == len(calls)
                and all(not row.get('error') for row in records)):
            charged = conservative = 0
            for call in calls:
                cost = call.get('cost_estimate_micro_usd')
                if call.get('cost_state') == 'estimated':
                    if type(cost) is not int or not 0 <= cost <= manifest['cost_policy']['role_reservation_micro_usd']:
                        raise ValueError('invalid completed role cost')
                    charged += cost
                elif call.get('cost_state') == 'conservative_reservation':
                    charged += manifest['cost_policy']['role_reservation_micro_usd']
                    conservative += 1
                else:
                    raise ValueError('completed role cost state missing')
            if charged != budget['charged_micro_usd'] or conservative != budget['conservative_roles']:
                raise ValueError('completed cost ledger mismatch')
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
        'incomplete_flows': [f['id'] for f in manifest['flows'] if f['id'] in started - completed],
        'unexecuted_flows': [f['id'] for f in manifest['flows'] if f['id'] not in started],
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
        'automatic_passed': end.get('reason') == 'completed'
                            and len(completed) == len(manifest['flows']) and not errors and not unreadable
                            and started_roles == len(calls) and started_requests == len(records)
                            and sum(r['seconds'] for r in records) <= manifest['limits']['seconds']
                            and all(r.get('reference_matched') is True for r in records),
        'costs': end.get('budget', {'actual_billing': None,
            'charged_micro_usd': started_roles * manifest['cost_policy']['role_reservation_micro_usd'],
            'conservative_roles': started_roles, 'basis': 'interrupted run conservative reservation'}),
        'role_usage': {role: {key: {'known_total': usage_totals[role, key],
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
    lock_path = Path(lock_path or private_root()/'launch-model.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    cancelled = cancelled or threading.Event()
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another launch evaluation owns the model') from None
        claim = {'run_id': uuid.uuid4().hex, 'manifest_sha256': qa.digest(private_bytes(directory, 'manifest.json')),
                 'controller_pid': os.getpid(), 'controller_birth': qa.process_birth(os.getpid())}
        qa.save(directory/'run-started.json', claim)
        for name in ('results', 'requests', 'calls'):
            (directory/name).mkdir(mode=0o700)
        done, lost = threading.Event(), threading.Event()
        claim_hash = qa.digest(private_bytes(directory, 'run-started.json'))

        def owned():
            try:
                return (os.fstat(lock.fileno()).st_ino == lock_path.stat().st_ino
                        and claim_hash == qa.digest(private_bytes(directory, 'run-started.json')))
            except (OSError, ValueError):
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
                               request_id=ident, flow=flow['id'], step=step, request_kind=data['request_kind'],
                               result_file=f'{budget.requests - 1:03d}.json', calls=[])
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
                            binding = dict(request_id=ident, role=role, run_id=claim['run_id'],
                                manifest_sha256=claim['manifest_sha256'], input_sha256=qa.digest(qa.encoded(sent)))
                            qa.save(directory/'calls'/f'{ident}-{role}.json',
                                    binding)
                            row['calls'].append({**binding, 'requested_effort': manifest['effort'],
                                                 'error': 'runner_failed'})
                            result = invoke(role, manifest['prompts'][role], schema, sent, deadline, cancelled)
                            row['calls'][-1].pop('error')
                            row['calls'][-1].update(result)
                            settlement = budget.settle(row['calls'][-1])
                            qa.save(directory/'calls'/f'{ident}-{role}.receipt',
                                {**binding, 'record_sha256': qa.digest(qa.encoded(row['calls'][-1]))})
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
                    qa.save(directory/'results'/row['result_file'], row)
                    qa.save(directory/'requests'/f'{ident}.receipt',
                        {key: row[key] for key in ('run_id', 'manifest_sha256', 'request_id', 'result_file')}
                        | {'record_sha256': qa.digest(qa.encoded(row))})
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
    frozen.add_argument('--flow', help='freeze only this launch flow id')
    frozen.add_argument('--max-smaller', type=int, help='smaller steps allowed in --flow')
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
                   monthly_spent_micro_usd=args.monthly_spent_micro_usd,
                   flow=args.flow, max_smaller=args.max_smaller)
            print(json.dumps({'frozen': True, 'model_calls': 0}))
            return 0
        if args.command == 'run':
            summary = run(args.directory, claude=args.claude)
        elif args.command == 'report':
            if Path(args.output).name != args.output or args.output in {'manifest.json', 'integrity.json'}:
                raise ValueError('report filename required')
            observations = private_json(args.observations.parent, args.observations.name, expected_type=list) if args.observations else []
            summary = report(args.directory, observations=observations)
            qa.save(args.directory/args.output, summary)
        else:
            summary = paid_preflight(args.stage, private_json(args.conditions.parent, args.conditions.name))
            print(json.dumps(summary))
            return 0 if summary['ready'] else 1
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary['automatic_passed'] else 1
    except (ValueError, OSError, KeyError, TypeError, RecursionError, subprocess.SubprocessError):
        # Paths, provider exceptions and input values belong only in the private bundle.
        print(json.dumps({'error': 'launch_evaluation_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""One approved, sequential #111 screen measurement. No CLI or implicit model calls.

The local observer prepares a fresh synthetic DB state, taps once, and returns the
existing XCTest observation, UUID-matched app record and PNG before the next slot.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import os
from pathlib import Path
from time import monotonic
import uuid

import launch_evaluation as launch
import oauth_quality as qa


CASES = (
    ('A', '책상 위 책 6권을 아래 책장 칸으로 옮기기',
     '책 6권과 빈 아래 칸이 모두 앉은 자리에서 손이 닿는다.', '책 6권을 모두 아래 칸으로 옮겼다.'),
    ('B', '영어 두 문장을 한국어로 번역해 문서에 적기',
     '번역할 원문은 The window is closed. / The door is open. 이며 빈 문서가 열려 있다.',
     '제공된 두 문장의 한국어 번역이 문서에 적혀 있다.'),
    ('C', '분기 보고서 목차 3개와 성과 3줄을 작성해 저장하기',
     '빈 문서가 열려 있다. 합성 성과: 모의 API 로그인 검사 통과, 프로필 UI 초안 완료, 배포 절차 초안 작성.',
     '목차 3개와 제공한 합성 성과 3줄이 문서에 적혀 저장됐다.'),
    ('D', '펜 5개를 펜꽂이에 정리하기',
     '손이 닿는 곳에 펜 5개와 빈 펜꽂이 1개가 있다.', '펜 5개가 모두 펜꽂이에 들어 있다.'),
    ('E', '책 18권을 라벨에 맞는 책장 3칸으로 분류하기',
     'A/B/C 라벨의 책이 각 6권 있다. 같은 라벨의 빈 책장 3칸과 책이 모두 손이 닿는다.',
     '책 18권이 각 책의 A/B/C 라벨과 같은 칸에 들어 있다.'),
)
LIMITS = {'requests': 20, 'calls': 40, 'generate': 20, 'check': 20, 'seconds': 3600}
SOURCES = ('scripts/screen_evaluation.py', 'scripts/screen_observer.py', 'scripts/oauth_bridge.py', 'scripts/oauth_quality.py',
           'apps/ios/TimingUITests/ScreenTimingTests.swift',
           'apps/ios/Packages/SmallnextCore/Sources/SmallnextCore/HTTPActionSuggestionProvider.swift',
           'apps/ios/Packages/SmallnextCore/Sources/SmallnextCore/ProgressFlow.swift',
           'services/api/src/development_ai.rs', 'services/api/src/suggestion.rs',
           'services/api/src/suggestion/compact.rs') + tuple(
               f'services/api/src/suggestion/{name}' for name in
               ('generate.md', 'check.md', 'contract.md', 'generate.json', 'check.json'))


def slots():
    first = [(case, kind) for case in CASES for kind in ('first_action', 'smaller')]
    result = []
    for index, (case, kind) in enumerate(first + list(reversed(first))):
        ident, goal, facts, criteria = case
        remaining = [criteria] + ([goal] if kind == 'smaller' else [])
        seed = {'status': 'action', 'action': goal, 'completion_condition': criteria,
                'estimated_minutes': 5, 'reason': '현재 미완료 행동', 'remaining_work': remaining,
                'goal_completed': False, 'current_action_completed': False, 'preserved_completed_ids': []}
        # Match the existing Swift transport, including the independent unfinished current action.
        data = {'goal': goal, 'current_blocker': '', 'user_request':
                '지금 시작할 첫 행동 하나를 제안한다.' if kind == 'first_action' else
                '현재 행동을 실질적으로 줄인다. 반복 막힘이면 알려진 답을 다시 묻지 않고 첫 막힘 한 가지를 확인한다.',
                'available': ['확정 완료 조건: ' + criteria, '현재 상태: ' + facts], 'unknown': [],
                'available_minutes': 5, 'knowledge': '사용자가 제공한 정보 외에는 모름', 'energy': '모름',
                'remaining_work': remaining, 'completed_ids': [],
                'previous_proposals': [seed] if kind == 'smaller' else [], 'request_kind': kind}
        result.append({'id': f'{index:02d}-{ident}-{kind}', 'candidate': ident, 'input': data,
                       'goal': goal, 'facts': facts, 'criteria': criteria, 'synthetic_state': True})
    return result


def freeze(directory, *, owner, ends_at, delete_method, claude, observer):
    directory = Path(directory).absolute()
    root = launch.private_root()
    if directory.parent != root or directory.is_symlink():
        raise ValueError('new private main-checkout work bundle required')
    end = datetime.fromisoformat(ends_at)
    if not owner.strip() or not delete_method.strip() or end.tzinfo is None or end <= datetime.now(timezone.utc):
        raise ValueError('owner and future retention cutoff required')
    sources = {name: qa.digest((qa.REPO / name).read_bytes()) for name in SOURCES}
    manifest = {'version': 1, 'plan': 'screen-111-once', 'slots': slots(), 'limits': LIMITS,
                'sources': sources, 'model': qa.MODEL, 'effort': qa.EFFORT,
                'output_mode': 'text-json', 'output_tokens': qa.OUTPUT_TOKENS,
                'claude': str(Path(claude).resolve()), 'cli_sha256': qa.digest(Path(claude).read_bytes()),
                'observer': str(Path(observer).resolve()), 'observer_sha256': qa.digest(Path(observer).read_bytes()),
                'pipeline_seconds': 120, 'screen_seconds': 180,
                'retention': {'owner': owner, 'evaluation_ends_at': end.isoformat(),
                              'delete_by': (end + timedelta(days=30)).isoformat(), 'delete_method': delete_method}}
    directory.mkdir(mode=0o700, exist_ok=False)
    for name in ('armed', 'calls', 'samples'):
        (directory / name).mkdir(mode=0o700)
    qa.save(directory / 'manifest.json', manifest)
    qa.save(directory / 'integrity.json', {'manifest_sha256': qa.digest(qa.encoded(manifest))})
    return manifest


def load(directory):
    manifest = launch.private_json(directory, 'manifest.json')
    if (qa.digest(qa.encoded(manifest)) != launch.private_json(directory, 'integrity.json')['manifest_sha256']
            or manifest['plan'] != 'screen-111-once' or manifest['version'] != 1
            or manifest['slots'] != slots() or manifest['limits'] != LIMITS
            or manifest['model'] != qa.MODEL or manifest['effort'] != qa.EFFORT
            or manifest['output_mode'] != 'text-json' or manifest['output_tokens'] != qa.OUTPUT_TOKENS
            or manifest['pipeline_seconds'] != 120 or manifest['screen_seconds'] != 180):
        raise ValueError('screen plan changed')
    if any(qa.digest((qa.REPO / name).read_bytes()) != manifest['sources'].get(name) for name in SOURCES):
        raise ValueError('screen source changed')
    if any(qa.digest(Path(manifest[path]).read_bytes()) != manifest[sha]
           for path, sha in (('claude', 'cli_sha256'), ('observer', 'observer_sha256'))):
        raise ValueError('CLI or observer changed')
    return manifest


def live(directory):
    if (directory / 'run-ended.json').exists() or (directory / 'stopped.json').exists():
        return False
    try:
        claim = launch.private_json(directory, 'run-started.json')
        lock = Path(claim['lock_path'])
        return (claim['approved_once'] is True and qa.process_birth(claim['controller_pid']) == claim['controller_birth']
                and claim['controller_birth']
                and claim['manifest_sha256'] == launch.private_json(directory, 'integrity.json')['manifest_sha256']
                and lock.stat().st_ino == claim['lock_inode'])
    except (OSError, ValueError, KeyError):
        return False


def stop(directory, reason):
    try:
        qa.save(directory / 'stopped.json', {'reason': reason})
    except FileExistsError:
        pass


class Cancelled:
    def __init__(self, directory, parent, deadline):
        self.directory, self.parent, self.deadline = directory, parent, deadline

    def is_set(self):
        # Parent loss reaps the CLI even when Rust kills the bridge without a handler.
        return self.parent.is_set() or not live(self.directory) or monotonic() >= self.deadline


def role_call(directory, data, invoke, parent, *, clock=monotonic):
    """The bridge admits exactly G then C for the currently armed immutable slot."""
    directory = Path(directory)
    manifest = load(directory)
    if datetime.now(timezone.utc) >= datetime.fromisoformat(manifest['retention']['evaluation_ends_at']):
        stop(directory, 'evaluation_cutoff')
        raise ValueError('evaluation cutoff reached')
    role = 'check' if 'candidate' in data else 'generate'
    original = data.get('original_request') if role == 'check' else data
    with (directory / 'admission.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not live(directory):
            raise ValueError('screen execution inactive')
        names = sorted((directory / 'armed').glob('*.json'))
        if not names:
            raise ValueError('no armed request')
        active = launch.private_json(directory, 'armed/' + names[-1].name)
        index = active['index']
        slot = manifest['slots'][index]
        if original != slot['input'] or (directory / 'samples' / f'{index:02d}.json').exists():
            stop(directory, 'input_or_order_mismatch')
            raise ValueError('frozen input or order mismatch')
        started = directory / 'calls' / f'{index:02d}-{role}-started.json'
        if role == 'check':
            generated = launch.private_json(directory, f'calls/{index:02d}-generate.json')
            if generated.get('error') or data['candidate'] != generated.get('output'):
                stop(directory, 'candidate_mismatch')
                raise ValueError('candidate mismatch')
            role_started = launch.private_json(directory, f'calls/{index:02d}-generate-started.json')['started']
        else:
            role_started = clock()
        deadline = min(role_started + 120, active['total_deadline'])
        if clock() >= deadline or parent.is_set():
            stop(directory, 'time_limit')
            raise ValueError('screen time limit')
        if len(list((directory / 'calls').glob('*-started.json'))) >= 40:
            stop(directory, 'call_limit')
            raise ValueError('screen call limit')
        try:
            qa.save(started, {'slot': slot['id'], 'started': role_started, 'payload_sha256': qa.digest(qa.encoded(data))})
        except FileExistsError:
            stop(directory, 'duplicate_role')
            raise ValueError('duplicate screen role') from None
    record = invoke(deadline, Cancelled(directory, parent, deadline))
    output = record.get('output', {})
    error = record.get('error')
    if not error and (record.get('actual_models') != [qa.MODEL] or record.get('provider_messages') != 1
                      or record.get('provider_retries', 0) or record.get('additional_provider_requests', 0)
                      or record.get('process_reaped') is not True or record.get('process_group_alive')):
        error = 'model_call_or_cleanup'
    usage = record.get('usage', {})
    if not error and any(qa.numeric(usage.get(key)) is None for key in ('input_tokens', 'output_tokens')):
        error = 'usage_unknown'
    if not error and (usage['output_tokens'] % 1 or usage['output_tokens'] > qa.OUTPUT_TOKENS):
        error = 'output_tokens_exceeded'
    if not error and (clock() >= deadline or not live(directory) or parent.is_set()):
        error = 'time_limit_or_cancelled'
    if not error and role == 'generate' and (qa.proposal_invalid_fields(original, output)
                                            or output.get('status') not in ('action', 'need_info')):
        error = 'invalid_or_non_normal_proposal'
    if not error and role == 'check' and (not qa.check_valid(output) or output.get('verdict') != 'accept'):
        error = 'unexpected_quality'
    if error:
        record['error'] = error
        stop(directory, error)
    qa.save(directory / 'calls' / f'{index:02d}-{role}.json', record)
    return record


def archive(directory, index, observation, app, png):
    """Publish all evidence before admitting another request; never depend on the 16-entry cache."""
    manifest = load(directory)
    ident = observation.get('run_id')
    uuid.UUID(ident)
    kind = manifest['slots'][index]['input']['request_kind']
    checked = launch.private_json(directory, f'calls/{index:02d}-check.json')
    generated = launch.private_json(directory, f'calls/{index:02d}-generate.json')
    status = generated['output']['status']
    outcome = 'question' if status == 'need_info' else 'action'
    elapsed = observation.get('observed_upper_seconds')
    server = app.get('server', {})
    if (checked.get('error') or generated.get('error') or checked['output']['verdict'] != 'accept'
            or observation.get('termination') != 'observed' or observation.get('missing_screenshot') is not False
            or observation.get('request_kind') != kind or observation.get('expected_outcome') != outcome
            or app.get('runID') != ident or app.get('requestKind') != kind or app.get('outcome') != outcome
            or server.get('run_id') != ident or qa.numeric(server.get('total_ms')) is None
            or any(qa.numeric(server.get(key)) is None for key in ('generate_ms', 'check_ms'))
            or qa.numeric(elapsed) is None or elapsed > 180
            or observation.get('budget_seconds') != 180
            or not png.startswith(b'\x89PNG\r\n\x1a\n') or qa.digest(png) != observation.get('evidence_sha256')
            or qa.numeric(observation.get('max_sample_interval_seconds')) is None
            or any(launch.private_json(directory, f'samples/{i:02d}.json')['observation']['run_id'] == ident
                   for i in range(index))):
        raise ValueError('missing, invalid or mismatched screen evidence')
    image = directory / 'samples' / f'{index:02d}.png'
    with image.open('xb') as stream:
        os.chmod(image, 0o600)
        stream.write(png)
        stream.flush()
        os.fsync(stream.fileno())
    qa.save(directory / 'samples' / f'{index:02d}.json',
            {'slot': manifest['slots'][index]['id'], 'observation': observation, 'app': app,
             'pixel_review': 'pending', 'screenshot_sha256': qa.digest(png)})


def run(directory, observe, *, approved_once=False, clock=monotonic):
    """Observe returns (XCTest observation, current UUID's app cache record, PNG bytes).

    Prepare/build the observer first. Its own failure propagates and ends this run;
    there is no retry, resume, replacement or model smoke path.
    """
    if approved_once is not True:
        raise ValueError('screen measurement requires explicit one-run approval')
    directory = Path(directory)
    manifest = load(directory)
    if datetime.now(timezone.utc) >= datetime.fromisoformat(manifest['retention']['evaluation_ends_at']):
        raise ValueError('evaluation cutoff reached')
    lock_path = launch.private_root() / 'launch-model.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another evaluation owns the model') from None
        qa.save(directory / 'run-started.json',
                {'approved_once': True, 'controller_pid': os.getpid(), 'controller_birth': qa.process_birth(os.getpid()),
                 'lock_path': str(lock_path), 'lock_inode': os.fstat(lock.fileno()).st_ino,
                 'manifest_sha256': qa.digest(qa.encoded(manifest))})
        started, reason = clock(), 'completed'
        try:
            for index, slot in enumerate(manifest['slots']):
                if not live(directory) or clock() - started >= 3600:
                    raise ValueError('stopped_or_time_limit')
                qa.save(directory / 'armed' / f'{index:02d}.json',
                        {'index': index, 'total_deadline': started + 3600})
                observation, app, png = observe(index, deepcopy(slot), min(180, started + 3600 - clock()))
                archive(directory, index, observation, app, png)
                if not live(directory) or clock() - started >= 3600:
                    raise ValueError('stopped_or_time_limit')
        except BaseException:
            reason = 'stopped'
            stop(directory, 'observation_or_execution_failed')
            raise
        finally:
            ended = datetime.now(timezone.utc)
            qa.save(directory / 'run-ended.json', {'reason': reason, 'elapsed_seconds': clock() - started,
                    'ended_at': ended.isoformat(), 'delete_by': min(ended + timedelta(days=30),
                    datetime.fromisoformat(manifest['retention']['delete_by'])).isoformat()})


def report(directory):
    directory = Path(directory)
    manifest = load(directory)
    measurement = {'minimum_p90_samples': 10, 'median_seconds': 20, 'p90_seconds': 30}
    values = {'first_action': [], 'smaller': []}
    pending = []
    for index, slot in enumerate(manifest['slots']):
        sample = directory / 'samples' / f'{index:02d}.json'
        if not sample.exists():
            continue
        row = launch.private_json(directory, f'samples/{index:02d}.json')
        if qa.digest(launch.private_bytes(directory, f'samples/{index:02d}.png')) != row['screenshot_sha256']:
            raise ValueError('screen image changed')
        if not (directory / 'samples' / f'{index:02d}-review.json').exists():
            pending.append(slot['id'])
            continue
        review = launch.private_json(directory, f'samples/{index:02d}-review.json')
        if review.get('screenshot_sha256') != row['screenshot_sha256']:
            raise ValueError('screen review evidence differs')
        if review.get('visible_normal_result') is True and review.get('basis') == 'agent_pixel_review':
            values[slot['input']['request_kind']].append(row['observation']['observed_upper_seconds'])
    return {'timings': {kind: launch.metrics(times, measurement) for kind, times in values.items()},
            'pending_pixel_reviews': pending, 'planned_requests': 20,
            'started_roles': len(list((directory / 'calls').glob('*-started.json'))),
            'ended': launch.private_json(directory, 'run-ended.json')}

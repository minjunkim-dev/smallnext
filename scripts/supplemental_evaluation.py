"""Fixed offline #287 plan data; no transport or automatic quality judgement."""
from copy import deepcopy
from datetime import datetime, timedelta
import json

import oauth_quality as qa


PLAN_ID = 'supplemental-fixed-v1'
FIXTURE = 'contracts/fixtures/supplemental-evaluation.json'
REFERENCE = 'contracts/fixtures/insufficient-info.json'
SOURCE_PATHS = (FIXTURE, REFERENCE, 'scripts/supplemental_evaluation.py',
                'docs/research/claude-output-limit-support.json')
CHECK_IDS = ('no-source-or-answer', 'useful-source-check', 'real-unanswered-question',
             'conflicting-sources', 'source-omission-is-not-absence', 'memory-without-details',
             'known-unknown-rewrite', 'unsupported-fill-in', 'specific-user-statement')


def fixed_flows():
    fixture = json.loads((qa.REPO / FIXTURE).read_bytes())
    if (fixture['id'] != PLAN_ID or fixture['order'] != dict(repeats=[1, 2, 3],
            groups=['fixed-checks', 'supplemental-flows'],
            request_kinds=['first_action', 'next_action', 'smaller', 'replacement'],
            branches=['new-facts', 'still-unknown'])):
        raise ValueError('unsupported fixed schedule')
    raw = (qa.REPO / REFERENCE).read_bytes()
    reference = json.loads(raw)
    checks = {case['id']: case for case in reference['checker_cases']}
    flows = []
    for repeat in range(1, 4):
        for ident in CHECK_IDS:
            case = checks[ident]
            candidate = case.get('generated', reference['generated'])
            flows.append(dict(id=f'{ident}-{repeat}', case_id=ident, kind='check', repeat=repeat,
                input=deepcopy(case['input']), candidate=deepcopy(candidate), max_smaller=0,
                expected=dict(statuses=[candidate['status']], verdicts=[case['check']['verdict']],
                              meaning=case['check']['reason']),
                reference=dict(path=REFERENCE, source_sha256=qa.digest(raw), case_id=ident,
                    input_sha256=qa.digest(qa.encoded(case['input'])),
                    candidate_sha256=qa.digest(qa.encoded(candidate)),
                    expected_sha256=qa.digest(qa.encoded(case['check'])))))
        for case in fixture['flows']:
            data = deepcopy(fixture['initial'])
            data.update(deepcopy(fixture['starts'][case['request_kind']]))
            after = deepcopy(data)
            supplement = fixture['supplements'][case['branch']]
            after['available'].append(fixture['supplement_prefix'] + supplement['text'])
            after['user_request'] = fixture['rerequest_instruction'][case['request_kind']]
            expected = dict(statuses=['insufficient_info'], verdicts=['accept'],
                            meaning=fixture['initial_meaning'], termination='supplement_then_explicit_rerequest')
            rerequest = dict(input=after, supplement=deepcopy(supplement),
                expected=dict(statuses=['action', 'minimum'] if case['branch'] == 'new-facts' else ['insufficient_info'],
                              verdicts=['accept'], meaning=case['meaning'], termination='rerequest_complete'))
            flows.append(dict(id=f"{case['id']}-{repeat}", case_id=case['id'], kind='generate_check',
                repeat=repeat, branch=case['branch'], input=data, expected=expected,
                max_smaller=0, rerequest=rerequest, synthetic_start=True,
                offline_review=dict(initial=fixture['initial_review'],
                                    supplement=supplement['offline_review'], reviewed_before_model_output=True)))
    return flows


def binding(manifest):
    return qa.digest(qa.encoded({key: value for key, value in manifest.items() if key != 'plan_sha256'}))


def validate(manifest):
    if (manifest.get('plan_id') != PLAN_ID or manifest.get('flows') != fixed_flows()
            or manifest.get('plan_sha256') != binding(manifest)):
        raise ValueError('fixed supplemental plan changed')
    retention = manifest['retention']
    if (any(type(retention.get(key)) is not str or not retention[key].strip()
            for key in ('location', 'owner', 'evaluation_ends_at', 'delete_by', 'delete_method'))
            or manifest.get('output_token_limit') != qa.OUTPUT_TOKENS
            or type(manifest.get('output_token_limit')) is not int):
        raise ValueError('fixed retention or output limit missing')
    end = datetime.fromisoformat(retention['evaluation_ends_at'])
    delete_by = datetime.fromisoformat(retention['delete_by'])
    if end.tzinfo is None or delete_by.tzinfo is None or delete_by > end + timedelta(days=30):
        raise ValueError('fixed retention limit changed')
    for path in SOURCE_PATHS:
        if manifest['sources'].get(path, {}).get('sha256') != qa.digest((qa.REPO / path).read_bytes()):
            raise ValueError('fixed supplemental source changed')
    for role in ('generate', 'check'):
        base = 'services/api/src/suggestion/'
        prompt = manifest['sources'][base + role + '.md']['utf8'] + '\n' + manifest['sources'][base + 'contract.md']['utf8']
        if (manifest['prompts'].get(role) != prompt
                or manifest['schemas'].get(role) != json.loads(manifest['sources'][base + role + '.json']['utf8'])):
            raise ValueError('fixed supplemental prompt or schema changed')


def steps(flow):
    return 2 if 'rerequest' in flow else flow['max_smaller'] + 1


def transition(flow, candidate, verdict, step):
    expected = flow['expected'] if step == 0 else flow['rerequest']['expected']
    matched = candidate['status'] in expected['statuses'] and verdict in expected['verdicts']
    if not matched:
        return False, None, None
    if step == 0:
        return True, None, deepcopy(flow['rerequest']['input'])
    return True, 'rerequest_complete', None

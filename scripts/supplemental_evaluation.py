"""Fixed offline #287 plan data; no transport or automatic quality judgement."""
from copy import deepcopy
from datetime import datetime, timedelta
import json

import oauth_quality as qa


PLAN_ID = 'supplemental-fixed-v1'
ONCE_PLAN_ID = 'supplemental-once-v1'
FIXTURE = 'contracts/fixtures/supplemental-evaluation.json'
REFERENCE = 'contracts/fixtures/insufficient-info.json'
SOURCE_PATHS = (FIXTURE, REFERENCE, 'scripts/supplemental_evaluation.py',
                'scripts/supplemental_review.py',
                'docs/research/claude-output-limit-support.json')
REQUIRED_SOURCES = SOURCE_PATHS + ('scripts/oauth_quality.py', 'scripts/launch_evaluation.py',
    'services/api/src/suggestion.rs', 'services/api/src/suggestion/compact.rs',
    'services/api/src/suggestion/contract.md', 'services/api/src/suggestion/generate.md',
    'services/api/src/suggestion/check.md', 'services/api/src/suggestion/generate.json',
    'services/api/src/suggestion/check.json')
CHECK_IDS = ('no-source-or-answer', 'useful-source-check', 'real-unanswered-question',
             'conflicting-sources', 'source-omission-is-not-absence', 'memory-without-details',
             'known-unknown-rewrite', 'unsupported-fill-in', 'specific-user-statement')


# #304: reviewed #303 source bytes may be read for reports, never executed or rewritten.
LEGACY_REPORT_SOURCES = {
    'scripts/oauth_quality.py': 'a77278906d6c5e64ea12b538f50d773afc032ad990b039a7e49f0a9adeb128b5',
    'scripts/launch_evaluation.py': 'ff3af0c3201ff07783105b26306ba0bbfc986c81d05394b4f7159a80b1527c0e',
    'scripts/supplemental_evaluation.py': 'de4b8a8f007d227ed5bc2e5ca87dd2edaa878bf765311bfeb512237b11bda00e',
    'scripts/supplemental_review.py': '32c62290df6b122ec10c6938c543d15660813a5c2467cc300d1c857048646503',
    'docs/research/claude-output-limit-support.json': '50d6edec463da28e571d9dca93045fb1728368a1a66ba3e8b083003b9b7d7971',
    REFERENCE: 'e3181ca5616b57490951ebd87e5dcdf55bb271b47cc1caee4e08d143a3cddacb',
}


# #308: preserve read-only reporting of the reviewed #306 bundle after evidence cleanup.
ONCE_REPORT_SOURCES = {
    'scripts/oauth_quality.py': '86ad71aacde3015d63e644901e60875eb14e3bc30e62bdeee0f8636b517f1f65',
    'scripts/launch_evaluation.py': '34e1065ac8e5c772a9f7adc30c2eb3ca72b9d977866340c2ce93923f6884be14',
    'scripts/supplemental_evaluation.py': '29419f53f9ab19e6e5455c0669380139ec0beac14e0cf139c5ab0c1a1a46f166',
    'scripts/supplemental_review.py': 'fa720a9afc1afc84c6b9b44a0f2d0d7883416052a0cab17731e90f41d41e0e8d',
    'docs/research/claude-output-limit-support.json': '50d6edec463da28e571d9dca93045fb1728368a1a66ba3e8b083003b9b7d7971',
    REFERENCE: 'e3181ca5616b57490951ebd87e5dcdf55bb271b47cc1caee4e08d143a3cddacb',
}


def legacy_report_sources(manifest):
    for version, kind, sources in ((3, 'supplemental-fixed', LEGACY_REPORT_SOURCES),
                                   (4, 'supplemental-once', ONCE_REPORT_SOURCES)):
        if (manifest.get('version') == version and manifest.get('plan_kind') == kind
                and all(manifest['sources'].get(path, {}).get('sha256') == sha
                        for path, sha in sources.items())):
            return sources
    return {}


def fixed_flows(*, once=False, reference_raw=None):
    fixture = json.loads((qa.REPO / FIXTURE).read_bytes())
    if (fixture['id'] != PLAN_ID or fixture['order'] != dict(repeats=[1, 2, 3],
            groups=['fixed-checks', 'supplemental-flows'],
            request_kinds=['first_action', 'next_action', 'smaller', 'replacement'],
            branches=['new-facts', 'still-unknown'])):
        raise ValueError('unsupported fixed schedule')
    raw = (qa.REPO / REFERENCE).read_bytes() if reference_raw is None else reference_raw
    reference = json.loads(raw)
    checks = {case['id']: case for case in reference['checker_cases']}
    flows = []
    for repeat in range(1, 2 if once else 4):
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


def validate(manifest, *, for_report=False):
    once = manifest.get('plan_kind') == 'supplemental-once'
    legacy = legacy_report_sources(manifest) if for_report else {}
    reference_raw = manifest['sources'][REFERENCE]['utf8'].encode() if legacy else None
    if (manifest.get('plan_id') != (ONCE_PLAN_ID if once else PLAN_ID)
            or manifest.get('flows') != fixed_flows(once=once, reference_raw=reference_raw)
            or manifest.get('model') != qa.MODEL or manifest.get('effort') != qa.EFFORT
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
    for path in REQUIRED_SOURCES:
        expected = legacy.get(path, qa.digest((qa.REPO / path).read_bytes()))
        if manifest['sources'].get(path, {}).get('sha256') != expected:
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

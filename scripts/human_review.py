"""Read-only preparation for the retained Issue #115 first rejection; no model calls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

import launch_evaluation as launch
import oauth_quality as qa


RECEIPT = qa.REPO / 'docs/research/fixtures/subscription-launch-results.json'


def prepare(directory, *, receipt=None):
    receipt = json.loads(RECEIPT.read_bytes()) if receipt is None else receipt
    expected_rows = receipt['launch_rows'][:2]
    manifest_hash = receipt['launch_manifest_sha256']
    report = dict(run_version=receipt['run_version'], manifest_sha256=manifest_hash,
                  case_id=expected_rows[0]['flow'],
                  request_ids=[r['request_id'] for r in expected_rows],
                  ready=False, missing=[], mismatched=[], unreadable=[], links=[],
                  human_review='not_performed', quality_passed=None,
                  model_calls=0, paid_calls=0)

    def match(label, actual, expected):
        if actual != expected:
            report['mismatched'].append(label)

    def read(descriptor, name, expected_hash=None):
        try:
            with launch.private_source(descriptor, name) as source:
                raw = source.read(launch.REPORT_JSON_LIMIT + 1)
            if len(raw) > launch.REPORT_JSON_LIMIT:
                raise ValueError('oversized source')
            value = json.loads(raw)
            if type(value) is not dict:
                raise ValueError('invalid source type')
        except FileNotFoundError:
            report['missing'].append(name)
            return None
        except (OSError, ValueError, RecursionError):
            report['unreadable'].append(name)
            return None
        digest = qa.digest(raw)
        if expected_hash is not None:
            match(name, digest, expected_hash)
        report['links'].append(dict(path=name, sha256=digest, expected_sha256=expected_hash))
        return value

    def link(label, path, pointer, value, expected_hash):
        digest = qa.digest(qa.encoded(value))
        match(label, digest, expected_hash)
        report['links'].append(dict(label=label, path=path, pointer=pointer,
                                   sha256=digest, expected_sha256=expected_hash,
                                   encoding='oauth_quality.encoded JSON value'))

    try:
        with launch.private_directory(directory) as descriptor:
            manifest = read(descriptor, 'manifest.json', manifest_hash)
            claim = read(descriptor, 'run-started.json')
            if manifest is not None and claim is not None:
                match('run-started binding', (claim['run_id'], claim['manifest_sha256']),
                      (expected_rows[0]['run_id'], manifest_hash))
                flows = manifest['flows']
                index = next(i for i, f in enumerate(flows) if f['id'] == report['case_id'])
                data = deepcopy(flows[index]['input'])
                for step, expected in enumerate(expected_rows):
                    name = f'results/{step:03d}.json'
                    row = read(descriptor, name)
                    ident = expected['request_id']
                    request = read(descriptor, f'requests/{ident}.json')
                    completion = read(descriptor, f'requests/{ident}.receipt')
                    if row is None or request is None or completion is None:
                        break
                    binding = dict(run_id=expected['run_id'], manifest_sha256=manifest_hash,
                                   request_id=ident, flow=expected['flow'], step=expected['step'],
                                   request_kind=expected['request_kind'], result_file=f'{step:03d}.json')
                    for key, value in binding.items():
                        match(f'{name}:{key}', row.get(key), value)
                        match(f'requests/{ident}.json:{key}', request.get(key), value)
                    for key in ('run_id', 'manifest_sha256', 'request_id', 'result_file'):
                        match(f'requests/{ident}.receipt:{key}', completion.get(key), binding[key])
                    match(f'{name}:completion hash', qa.digest(qa.encoded(row)), completion['record_sha256'])
                    # Inputs were not stored separately; bind reconstruction to the original public payload hash.
                    input_hash = qa.digest(qa.encoded(data))
                    match(f'{name}:request input', request['input_sha256'], input_hash)
                    link(f'{step}:input', 'manifest.json', f'/flows/{index}/input', data,
                         expected['roles'][0]['payload_sha256'])
                    if step:
                        report['links'][-1]['previous_candidate'] = 'results/000.json#/calls/0/output'
                        report['links'][-1]['derivation'] = 'append previous candidate; request_kind=smaller; frozen runner user_request'
                    calls = row['calls']
                    match(f'{name}:role order', [c['role'] for c in calls], ['generate', 'check'])
                    if len(calls) != 2:
                        break
                    for role_index, public_call in enumerate(expected['roles']):
                        role = public_call['role']
                        call = calls[role_index]
                        sent = data if role == 'generate' else dict(original_request=data, candidate=calls[0]['output'])
                        sent_hash = qa.digest(qa.encoded(sent))
                        marker_name = f'calls/{ident}-{role}'
                        marker = read(descriptor, marker_name + '.json')
                        role_receipt = read(descriptor, marker_name + '.receipt')
                        for record in (call, marker, role_receipt):
                            if record is None:
                                continue
                            for key, value in dict(run_id=expected['run_id'], manifest_sha256=manifest_hash,
                                                   request_id=ident, role=role, input_sha256=sent_hash).items():
                                match(f'{marker_name}:{key}', record.get(key), value)
                        match(f'{marker_name}:payload', sent_hash, public_call['payload_sha256'])
                        match(f'{marker_name}:recorded payload', call.get('payload_sha256'), sent_hash)
                        if role_receipt is not None:
                            match(f'{marker_name}:completion hash', qa.digest(qa.encoded(call)),
                                  role_receipt['record_sha256'])
                        link(f'{step}:{role}:output', name, f'/calls/{role_index}/output',
                             call['output'], public_call['output_sha256'])
                    if step == 0:
                        data['previous_proposals'].append(deepcopy(calls[0]['output']))
                        data['request_kind'] = 'smaller'
                        data['user_request'] = '현재 행동을 실질적으로 줄인다. 반복 막힘이면 첫 막힘 한 가지를 확인한다.'
    except FileNotFoundError:
        report['missing'].append('bundle')
    except (OSError, ValueError, KeyError, TypeError, StopIteration, IndexError, RecursionError):
        report['unreadable'].append('bundle structure')
    report['ready'] = not any(report[key] for key in ('missing', 'mismatched', 'unreadable'))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='existing private launch bundle, read only')
    args = parser.parse_args()
    report = prepare(args.directory)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    sys.exit(main())

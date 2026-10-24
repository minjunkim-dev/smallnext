"""Hash-only review forms for the fixed offline plan; no execution or quality approval."""
from datetime import datetime, timedelta
import json

import oauth_quality as qa


DECISIONS = {'meets_expectation', 'generation_violation', 'checker_misjudgement',
             'technical_error', 'uncertain'}


def report(manifest, records, end, summary, review, record_hashes):
    support = qa.output_readiness(manifest['output_mode'])
    frozen_support = manifest['sources']['docs/research/claude-output-limit-support.json']['sha256']
    metadata = {}
    if frozen_support == qa.OUTPUT_SUPPORT_SHA256:
        evidence = json.loads(manifest['sources']['docs/research/claude-output-limit-support.json']['utf8'])
        metadata = {key: evidence[key] for key in ('checked_on', 'cli_version', 'cli_sha256', 'sources',
                    'authentication', 'transport', 'output_modes', 'scope', 'provider_observation')}
    if support.get('evidence_sha256') != frozen_support:
        support = dict(support, ready=False, reasons=[*support.get('reasons', []), 'frozen_support_mismatch'])
    units = {unit['request_id']: unit for unit in summary['units']}
    flows = {flow['id']: flow for flow in manifest['flows']}
    items, unavailable = [], []
    for row in records:
        unit = units[row['request_id']]
        flow = flows[row['flow']]
        candidate = (flow['candidate'] if flow['kind'] == 'check' else
                     next((call.get('output') for call in row['calls'] if call['role'] == 'generate'), None))
        checked = next((call.get('output') for call in row['calls'] if call['role'] == 'check'), None)
        for index, call in enumerate(row['calls']):
            if 'output' not in call:
                if call.get('started', True):
                    tokens = qa.numeric(call.get('usage', {}).get('output_tokens'))
                    characters = call.get('delta_characters', {})
                    counts_valid = (type(characters) is dict
                                    and all(type(value) is int and value >= 0 for value in characters.values()))
                    partial = (tokens is not None and tokens > 0 or call.get('error') == 'max_tokens'
                               or bool(call.get('max_tokens')) or counts_valid and any(characters.values()))
                    if partial or tokens is None or not counts_valid:
                        unavailable.append(dict(output_id=f"{row['request_id']}:{call['role']}",
                            request_id=row['request_id'], role=call['role'], result_file='results/' + row['result_file'],
                            metadata_pointer=f'/calls/{index}', record_sha256=record_hashes[row['request_id']],
                            reason='output_not_retained' if partial else 'output_inventory_unverified'))
                continue
            models = call.get('actual_models')
            observed_models = (sorted({name if name == qa.MODEL else 'unexpected_model' for name in models})
                               if type(models) is list and all(type(name) is str for name in models) else None)
            items.append(dict(output_id=f"{row['request_id']}:{call['role']}",
                request_id=row['request_id'], unit_id=unit['unit_id'], case_id=unit['case_id'],
                request_kind=unit['request_kind'], phase=unit['phase'], repeat=unit['repeat'], role=call['role'],
                result_file='results/' + row['result_file'], call_index=index,
                output_pointer=f'/calls/{index}/output', record_sha256=record_hashes[row['request_id']],
                input_sha256=call['input_sha256'], output_sha256=qa.digest(qa.encoded(call['output'])),
                candidate_sha256=qa.digest(qa.encoded(candidate)) if candidate is not None else None,
                check_sha256=qa.digest(qa.encoded(checked)) if checked is not None else None,
                expected_meaning_sha256=unit['expected_meaning_sha256'],
                reference_matched=unit['reference_matched'],
                recommendation='inspect_technical_error' if row.get('error') not in (None, 'unexpected_quality') else
                    'inspect_reference_mismatch' if unit['reference_matched'] is False else 'review_required',
                requested_model=manifest['model'], requested_effort=manifest['effort'], observed_effort=None,
                observed_models=observed_models,
                output_tokens=qa.numeric(call.get('usage', {}).get('output_tokens')),
                configuration_delivery='transport_reported' if call.get('output_token_limit') == qa.OUTPUT_TOKENS
                    else 'unverified',
                human_decision=None, human_reason_sha256=None))
    inventory = {item['output_id']: item for item in items}
    if len(inventory) != len(items):
        raise ValueError('duplicate review output')
    basis = 'not_performed'
    if review is not None:
        if (type(review) is not dict or set(review) != {'run_id', 'manifest_sha256', 'basis', 'entries'}
                or review['run_id'] != summary['run_id']
                or review['manifest_sha256'] != summary['manifest_sha256']
                or review['basis'] not in ('synthetic', 'declared_human')
                or type(review['entries']) is not list or len(review['entries']) > len(items)):
            raise ValueError('unrelated or invalid output review')
        basis, seen = review['basis'], set()
        for entry in review['entries']:
            if (type(entry) is not dict or set(entry) != {'output_id', 'output_sha256', 'decision', 'reason'}
                    or type(entry['output_id']) is not str or entry['output_id'] not in inventory
                    or entry['output_id'] in seen or type(entry['decision']) is not str
                    or entry['decision'] not in DECISIONS
                    or type(entry['reason']) is not str or not entry['reason'].strip()):
                raise ValueError('duplicate, unrelated or invalid review decision')
            seen.add(entry['output_id'])
            item = inventory[entry['output_id']]
            if entry['output_sha256'] != item['output_sha256']:
                raise ValueError('review output changed')
            if (entry['decision'] == 'generation_violation' and item['role'] != 'generate'
                    or entry['decision'] == 'checker_misjudgement' and item['role'] != 'check'):
                raise ValueError('review finding has wrong role')
            item.update(human_decision=entry['decision'], human_reason_sha256=qa.digest(qa.encoded(entry['reason'])))
    pending = [item['output_id'] for item in items if item['human_decision'] is None]
    pending.extend(item['output_id'] for item in unavailable)
    problems = [item['output_id'] for item in items if item['human_decision'] in
                ('generation_violation', 'checker_misjudgement')]
    deferred = [dict(unit_id=unit['unit_id'], reason=unit['reason'] or 'unverified_unit')
                for unit in summary['units'] if unit['state'] != 'completed']
    deferred.extend(dict(output_id=item['output_id'], reason=item['human_decision'] or 'unreviewed_output')
                    for item in items if item['human_decision'] in (None, 'technical_error', 'uncertain'))
    deferred.extend(dict(output_id=item['output_id'], reason=item['reason']) for item in unavailable)
    if summary['unreadable_records'] or summary['roles']['unrecorded'] or summary['requests']['unrecorded']:
        deferred.append(dict(reason='incomplete_record_inventory'))
    if not support['ready']:
        deferred.append(dict(reason='output_limit_support_incomplete'))
    accounted = (not summary['unreadable_records'] and not summary['roles']['unrecorded']
                 and not summary['requests']['unrecorded']
                 and all(unit['state'] == 'completed' or unit['reason'] for unit in summary['units'])
                 and bool(end))
    work_complete = basis != 'not_performed' and not pending and bool(accounted)
    fit = work_complete and summary['automatic_passed'] and not problems and not deferred
    template = dict(run_id=summary['run_id'], manifest_sha256=summary['manifest_sha256'],
                    basis='declared_human', entries=[dict(output_id=item['output_id'], output_sha256=item['output_sha256'],
                                                         decision=None, reason=None)
                                                    for item in items])
    assessment = dict(basis=basis, review_sha256=qa.digest(qa.encoded(review)) if review is not None else None,
        items=items, unavailable_outputs=unavailable, template=template, pending_outputs=pending, problem_outputs=problems,
        deferred_scopes=deferred, work_complete=work_complete, problem_found=bool(problems),
        state='synthetic_work_complete' if work_complete and basis == 'synthetic' else
              'declared_review_complete' if work_complete else 'awaiting_human_review',
        contract_fit='synthetic_fit' if fit and basis == 'synthetic' else
                     'declared_fit' if fit else 'deferred')
    retention = manifest['retention']
    frozen_deadline = datetime.fromisoformat(retention['delete_by'])
    deadline = frozen_deadline
    if end:
        ended = datetime.fromisoformat(end['ended_at'])
        recorded = datetime.fromisoformat(end['delete_by'])
        if ended.tzinfo is None or recorded.tzinfo is None:
            raise ValueError('retention timestamps require timezone')
        deadline = min(frozen_deadline, ended + timedelta(days=30))
        if recorded > deadline:
            raise ValueError('retention deadline extended')
        deadline = min(deadline, recorded)
    return dict(plan_id=manifest['plan_id'], plan_sha256=manifest['plan_sha256'],
        output_review=assessment,
        preparation=dict(support, actual_execution_authorized=False, frozen_evidence_sha256=frozen_support,
                         evidence_metadata=metadata, contract=manifest['contract'], plan_sha256=manifest['plan_sha256'],
                         configuration_delivery_count=sum(item['configuration_delivery'] == 'transport_reported'
                                                          for item in items)),
        retention=dict(delete_by=deadline.isoformat(), frozen_delete_by=frozen_deadline.isoformat(),
            owner_sha256=qa.digest(qa.encoded(retention['owner'])),
            delete_method_sha256=qa.digest(qa.encoded(retention['delete_method'])),
            location_sha256=qa.digest(qa.encoded(retention['location'])),
            scope='main_checkout_private_work', extended_by_report=False))

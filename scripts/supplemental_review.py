"""Hash-only review forms for the fixed offline plan; no execution or quality approval."""
from datetime import datetime, timedelta
import json

import oauth_quality as qa


DECISIONS = {'meets_expectation', 'generation_violation', 'checker_misjudgement',
             'technical_error', 'uncertain'}


def output_report(manifest, records, end, summary, review, record_hashes):
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
                or review['basis'] not in (('synthetic', 'declared_agent')
                    if manifest.get('plan_kind') == 'supplemental-once' else ('synthetic', 'declared_human'))
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


def report(manifest, records, end, summary, review, record_hashes, *, comparisons=False):
    if manifest.get('plan_kind') != 'supplemental-once':
        if comparisons:
            raise ValueError('comparisons require the single-repeat plan')
        return output_report(manifest, records, end, summary, review, record_hashes)
    if review is not None and (type(review) is not dict or set(review) != {'first_pass', 'human'}):
        raise ValueError('single-repeat review requires separate agent and human records')
    first_pass = review.get('first_pass') if review else None
    human = review.get('human') if review else None
    result = output_report(manifest, records, end, summary, first_pass, record_hashes)
    agent = result.pop('output_review')
    for item in agent['items']:
        item['agent_decision'] = item.pop('human_decision')
        item['agent_reason_sha256'] = item.pop('human_reason_sha256')
    agent['template']['basis'] = 'declared_agent'
    agent['state'] = ('synthetic_work_complete' if agent['basis'] == 'synthetic' else 'agent_review_complete') \
        if agent['work_complete'] else 'awaiting_agent_review'
    agent['contract_fit'] = 'not_a_human_verdict'
    by_request = {row['request_id']: row for row in records}
    reasons = {item['output_id']: item['reason'] for item in first_pass['entries']} if first_pass else {}
    cards = []
    for flow in manifest['flows']:
        phases, anomalies = [], []
        for unit in (unit for unit in summary['units'] if unit['id'] == flow['id']):
            row = by_request.get(unit['request_id'], {})
            calls = {call['role']: call for call in row.get('calls', [])}
            outputs = [item for item in agent['items'] if item['request_id'] == unit['request_id']]
            flags = ([unit['reason'] or 'unit_incomplete'] if unit['state'] != 'completed' else [])
            if unit['reference_matched'] is False:
                flags.append('reference_mismatch')
            if first_pass is not None and any(item['agent_decision'] is None for item in outputs):
                flags.append('agent_review_missing')
            flags.extend(item['agent_decision'] for item in outputs
                         if item['agent_decision'] not in (None, 'meets_expectation'))
            flags.extend(item['reason'] for item in agent['unavailable_outputs']
                         if item['request_id'] == unit['request_id'])
            anomalies.extend(flags)
            phases.append(dict(phase=unit['phase'], request_id=unit['request_id'], state=unit['state'],
                reason=unit['reason'], input=flow['input'] if unit['step'] == 0 else flow['rerequest']['input'],
                candidate=flow.get('candidate') if flow['kind'] == 'check' else calls.get('generate', {}).get('output'),
                checker=calls.get('check', {}).get('output'),
                evidence=[dict(output_id=item['output_id'], record_sha256=item['record_sha256'],
                    output_sha256=item['output_sha256'], agent_decision=item['agent_decision'],
                    agent_reason_sha256=item['agent_reason_sha256'],
                    agent_reason=reasons.get(item['output_id'])) for item in outputs]))
        if flow['kind'] == 'generate_check' or anomalies:
            cards.append(dict(card_id=flow['id'], kind='comparison' if flow['kind'] == 'generate_check' else 'anomaly',
                              case_id=flow['case_id'], request_kind=flow['input']['request_kind'],
                              branch=flow.get('branch'), anomalies=sorted(set(anomalies)), phases=phases,
                              first_pass_state='pending' if any(item['agent_decision'] is None
                                  for phase in phases for item in phase['evidence']) else 'reviewed'))
    if summary['unreadable_records'] or summary['roles']['unrecorded'] or summary['requests']['unrecorded'] \
            or not result['preparation']['ready']:
        cards.append(dict(card_id='record-inventory', kind='anomaly', phases=[],
                          anomalies=['record_inventory_or_preparation_incomplete']))
    # Bind the human card to private inputs, outputs and the exact first-pass findings.
    for card in cards:
        card['card_sha256'] = qa.digest(qa.encoded(dict(run_id=summary['run_id'],
            manifest_sha256=summary['manifest_sha256'], card=card)))
    inventory = {card['card_id']: card for card in cards}
    decisions, basis = {}, 'not_performed'
    if human is not None:
        if (type(human) is not dict or set(human) != {'run_id', 'manifest_sha256', 'basis', 'entries'}
                or human['run_id'] != summary['run_id'] or human['manifest_sha256'] != summary['manifest_sha256']
                or human['basis'] not in ('synthetic', 'declared_human') or type(human['entries']) is not list
                or len(human['entries']) > len(cards)):
            raise ValueError('invalid human comparison review')
        basis = human['basis']
        for entry in human['entries']:
            if (type(entry) is not dict or set(entry) != {'card_id', 'card_sha256', 'decision', 'reason'}
                    or type(entry['card_id']) is not str or entry['card_id'] not in inventory
                    or entry['card_id'] in decisions or entry['card_sha256'] != inventory[entry['card_id']]['card_sha256']
                    or type(entry['decision']) is not str or entry['decision'] not in DECISIONS
                    or type(entry['reason']) is not str or not entry['reason'].strip()):
                raise ValueError('duplicate, changed or invalid human comparison')
            decisions[entry['card_id']] = entry
    public = [dict(card_id=card['card_id'], card_sha256=card['card_sha256'], kind=card['kind'],
        output_ids=[item['output_id'] for phase in card['phases'] for item in phase['evidence']],
        anomalies=card['anomalies'], first_pass_state=card.get('first_pass_state', 'unverified'),
        human_decision=decisions.get(card['card_id'], {}).get('decision'),
        human_reason_sha256=qa.digest(qa.encoded(decisions[card['card_id']]['reason']))
                            if card['card_id'] in decisions else None) for card in cards]
    pending = [card['card_id'] for card in cards if card['card_id'] not in decisions]
    template = dict(run_id=summary['run_id'], manifest_sha256=summary['manifest_sha256'], basis='declared_human',
        entries=[dict(card_id=card['card_id'], card_sha256=card['card_sha256'], decision=None, reason=None)
                 for card in cards])
    complete = agent['work_complete'] and basis != 'not_performed' and not pending
    fit = (complete and summary['automatic_passed'] and not agent['deferred_scopes']
           and not agent['problem_found'] and all(entry['decision'] == 'meets_expectation' for entry in decisions.values()))
    synthetic = basis == 'synthetic' or agent['basis'] == 'synthetic'
    result.update(first_pass_review=agent, comparison_review=dict(basis=basis, cards=public,
        template=template, pending_cards=pending, human_complete=basis != 'not_performed' and not pending,
        work_complete=complete, contract_fit=('synthetic_fit' if synthetic else 'declared_fit') if fit else 'deferred',
        scope='eight_flow_comparisons_and_all_anomalies'))
    if comparisons:
        result['private_comparisons'] = dict(run_id=summary['run_id'],
            manifest_sha256=summary['manifest_sha256'], cards=cards)
    return result


def comparison_markdown(bundle):
    lines = ['# 평가 전후 비교와 이상 사례', '', '모델/에이전트의 판정과 사용자의 직접 판정은 별개입니다.', '',
             '실행: ' + bundle['run_id'], '계획 해시: ' + bundle['manifest_sha256'], '']
    labels = {'status': '상태', 'action': '제안', 'reason': '이유', 'completion_condition': '완료 조건',
              'estimated_minutes': '예상 분', 'facts': '근거', 'reduction': '줄어든 범위',
              'remaining_work': '남은 범위', 'goal_completed': '목표 완료 여부',
              'current_action_completed': '현재 행동 완료 여부', 'preserved_completed_ids': '보존된 완료 기록'}

    def block(value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        return ['    ' + line for line in (text.splitlines() or ['(없음)'])] + ['']

    for card in bundle['cards']:
        lines.extend(['## ' + card['card_id'], '', '검토 연결 해시: ' + card['card_sha256'], '',
                      '이상 사항', ''])
        lines.extend(block(', '.join(card['anomalies']) or
            ('1차 검토 대기: 아직 이상 없음으로 판정하지 않음' if card.get('first_pass_state') == 'pending'
             else '자동 검사/1차 검토에서 표시된 이상 없음')))
        for phase in card['phases']:
            title = {'initial': '보충 전', 'explicit_rerequest': '보충 후 재요청', 'fixed_check': '고정 답변 검사'}[phase['phase']]
            lines.extend(['### ' + title, '', '진행: ' + phase['state'], '', '입력과 보충 자료', ''])
            lines.extend(block(phase['input']))
            candidate = phase['candidate']
            if candidate is None:
                lines.extend(['답변 없음', '']); lines.extend(block(phase['reason'] or '미실행 또는 미확인'))
            else:
                for key, value in candidate.items():
                    lines.extend([labels.get(key, key), '']); lines.extend(block(value))
            lines.extend(['검사 모델 판정', '']); lines.extend(block(phase['checker']))
            for item in phase['evidence']:
                lines.extend(['에이전트 1차 판정 (' + item['output_id'] + ')', ''])
                lines.extend(block(item['agent_decision'] or '검토 대기'))
                lines.extend(block(item['agent_reason'] or '사유 아직 없음'))
    return '\n'.join(lines) + '\n'

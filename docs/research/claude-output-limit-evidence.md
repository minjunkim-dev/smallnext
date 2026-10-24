# Claude Code 출력 제한·내부 재시도 공식 근거 조사

확인일: 2026-10-25 KST. 대상: Smallnext #285 후속 조사, Claude Code 구독 OAuth, `claude-haiku-5-5`, `xhigh`, `-p --output-format stream-json --verbose --include-partial-messages --max-turns 1`, 애플리케이션의 `structured`·`text-json` 경로.

공개 공식 문서·공식 저장소 변경 이력과 설치본의 제한한 정적 바이트 범위를 조사했다. 이번 확인에서 설치 CLI를 실행하거나 계정·키·세션·과거 평가 원문을 읽지 않았다. 실제 모델 호출, 평가 freeze/run, 유료 API 사용, 키 생성은 수행하지 않았다. 공급자 요청·응답 관측은 없다. 설치본 식별자·분석 범위·해시는 [지원 근거 스냅샷](claude-output-limit-support.json)에 기록했다.

## 결론

8192 설정의 문서 근거는 확인되지만 대상 OAuth의 모든 내부 경로 적용을 증명하지는 못한다. 구독의 실제 상한·사고 집계·역할당 응답 1회는 **미확인**이다. [Claude Code 환경변수](https://code.claude.com/docs/en/env-vars)

문서로 식별되는 오류 재시도·스키마 검증 시도 제한은 오프라인 보완의 근거가 된다. 출력 상한 복구·사고만 생성한 응답·잘린 스트림 등 다른 내부 분기는 설치본에서 별도로 추적해야 한다. 공식 변경 이력은 출력 상한 뒤 자동 이어쓰기가 존재함을 명시한다. [Claude Code 공식 CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md#210)

## Claude Code 환경변수의 직접 근거

아래 행은 모두 [현재 영문 환경변수 문서](https://code.claude.com/docs/en/env-vars)의 `Variables` 표에서 확인했다. 긴 인용 대신 요약했다.

| 항목 | 공식 문서가 설명하는 범위 | 이번 판단 |
| --- | --- | --- |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | 대부분 요청의 최대 출력 토큰. 모델 cap 초과값은 cap으로 낮춘다. | 8192 설정 근거. 모든 요청 보장은 아님. |
| `MAX_THINKING_TOKENS` | 고정 사고 예산. 출력 상한보다 작게 제한되지만 adaptive 모델에서는 양수값 자체가 무시된다. | 8192 전체 출력 제한의 대체재가 아님. |
| `CLAUDE_CODE_MAX_RETRIES` | 실패한 API 요청의 재시도 횟수, 기본 10. | 공식 변수명. `0` 처리는 아래 설치본에서 확인. |
| `MAX_STRUCTURED_OUTPUT_RETRIES` | `-p --json-schema` 검증 실패 시 총 시도 횟수, 기본 5 = 최초 1 + 재시도 4. | 공식 변수명. 1은 최초 시도만 허용한다는 해석. |
| `CLAUDE_CODE_RETRY_WATCHDOG` | 켜면 429·529 재시도와 다른 일시 오류의 기본 재시도를 확대한다. | 상속 여부도 통제 대상. |
| `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK` | 중간 스트리밍 실패의 비스트리밍 전환을 끄고 오류를 retry layer로 전달한다. | 출력 상한 이어쓰기 전체 중단 근거는 아님. |
| `CLAUDE_CODE_RESUME_INTERRUPTED_TURN` | 중단된 이전 세션의 재개를 제어한다. unset 또는 0으로 끈다. | 현재 요청의 출력 상한 복구와 다른 문맥. |

`CLAUDE_CODE_MAX_STRUCTURED_OUTPUT_RETRIES`·`MAX_RETRIES`는 표에서 미발견이다. [환경변수](https://code.claude.com/docs/en/env-vars)

비스트리밍 fallback 변수는 공개 문서 도구가 반환한 704행 중 L291에서 확인했다. 최소 버전 표기는 없다. 설치본 도달 여부는 별도 증거다. [환경변수](https://code.claude.com/docs/en/env-vars)

## Haiku 5.5·xhigh와 사고 집계

Claude Code 모델 문서는 Haiku 5.5에 `xhigh`를 지원하며, 항상 adaptive reasoning을 사용한다고 설명한다. 이 경로에서는 `MAX_THINKING_TOKENS`의 양수 예산으로 사고량을 고정할 수 없고 `MAX_THINKING_TOKENS=0`으로도 사고를 끌 수 없다. 문서상 Haiku 5.5 사용 권장 최소 버전은 2.1.293이다. [모델 설정](https://code.claude.com/docs/en/model-config#adjust-effort-level), [사고 모드](https://code.claude.com/docs/en/model-config#thinking-mode)

**일반 API 계약:** 사고 토큰은 출력 토큰이며 응답 텍스트와 `max_tokens`를 공유한다. 숨겨진 사고도 포함된다. API 문서는 Haiku 5.5의 최대 출력 ceiling을 128K로 기재한다. 이것을 구독 OAuth에서 관측한 cap이라고 기록하면 안 된다. [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking#output-limits)

**요청과 전체 실행의 차이:** API의 `max_tokens`는 요청당 전체 출력의 상한이다. 도구 루프의 각 요청은 별도 상한을 가지므로 전체 turn 비용을 제한하지 않는다. `effort`는 사고량에 대한 유연한 지침이며 토큰 수를 보장하지 않는다. 따라서 8192를 “역할 실행 전체의 누적 토큰 상한”으로 확대 해석할 수 없다. [Steering thinking: cost control](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost#cost-control)

**문서 범위 차이:** 일반 API는 Haiku 5.5의 `thinking.type=disabled`를 `high` 이하에서 허용하지만 `xhigh`·`max`에서는 거부한다고 설명한다. Claude Code 문서는 Haiku 5.5에서 사고를 끌 수 없다고 설명한다. 이번 `xhigh` 경로에서는 사고 중단 수단이 없다는 방향이 같지만, API의 직접 파라미터 계약을 CLI의 설정 계약으로 대체해서는 안 된다. [Thinking: configuring thinking](https://platform.claude.com/docs/en/build-with-claude/thinking#configuring-thinking), [Claude Code 사고 모드](https://code.claude.com/docs/en/model-config#thinking-mode)

## print·stream-json·구조화 출력의 범위

| 항목 | 공식 근거 | 한계 |
| --- | --- | --- |
| `--max-turns 1` | print 모드의 agentic turn 제한. [CLI reference](https://code.claude.com/docs/en/cli-reference#cli-flags) | 내부 공급자 요청 1회 제한이라는 문구는 없음. |
| `--output-format stream-json`·`--include-partial-messages` | print 출력 형식과 부분 스트림 이벤트를 선택. [CLI reference](https://code.claude.com/docs/en/cli-reference#cli-flags) | 출력 형식이 공급자 재시도·사고 집계 규칙을 바꾼다는 근거는 없음. |
| `--json-schema` | agent workflow 뒤 스키마 검증된 JSON을 받는 print 옵션. [CLI reference](https://code.claude.com/docs/en/cli-reference#cli-flags) | `structured` 경로의 검증 시도 제한 근거와 연결 가능. |
| 구조화 출력 실패 | 유효한 출력이 남지 않으면 `error_max_structured_output_retries`; 검증 실패 외 모델 fallback으로 완료 출력이 철회된 경우도 포함. [Agent SDK 구조화 출력](https://code.claude.com/docs/en/agent-sdk/structured-outputs#error-handling) | 단순 JSON 파싱 실패나 전체 재요청 수와 동일시하면 안 됨. |

`structured`·`text-json`은 이 조사에서 대상 애플리케이션의 경로명이다. 공식 CLI 출력 형식은 `text`, `json`, `stream-json`이며 `text-json`이라는 형식을 기재하지 않는다. 따라서 `--json-schema`가 없는 `text-json` fallback에도 동일 검증 재시도 루프가 적용된다고 가정하지 않는다. [CLI reference](https://code.claude.com/docs/en/cli-reference#cli-flags)

## 자동 이어쓰기와 설정 우선순위

공식 CHANGELOG의 2.1.0 항목은 출력 상한으로 잘린 응답을 오류로 끝내는 대신 자동으로 계속하도록 개선했다고 설명한다. 현재 변경 이력에는 비스트리밍 전환 뒤 출력 상한 응답이 재시도나 오류 없이 조용히 끝나는 문제의 수정도 있다. 이는 자동 복구의 존재 근거이며, 횟수·예산 확대·설정으로 중단하는 방법의 완전한 계약은 아니다. [공식 CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md#210), [확인한 원문](https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md)

셸·settings·CLI flag가 같은 동작을 설정할 때 우선순위는 항목별로 다르다. settings 파일의 `env`가 상속한 셸 값을 덮어쓰는 경우도 있으므로, 자식 환경 dict를 고정한 오프라인 검사는 그 dict를 확인한 증거로 한정해야 한다. [Settings files and precedence](https://code.claude.com/docs/en/settings#settings-precedence), [환경변수 우선순위](https://code.claude.com/docs/en/env-vars#precedence)

## 구현한 오프라인 보완

기존 자식 환경에 `CLAUDE_CODE_MAX_RETRIES=0`, `MAX_STRUCTURED_OUTPUT_RETRIES=1`, `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1`을 고정했다. 부모의 큰 재시도 값이나 watchdog는 상속하지 않는다. 기존8192·구독 강제·모델/effort·설정 출처 차단·도구/hooks/MCP 차단을 유지한다.

생성·검사와 두 출력 경로에서 가짜 CLI가 받은 값 및 정상 결과·오류 뒤 회수를 검증한다. 이는 가짜 프로세스의 전달 검증이며 실제 CLI 내부 실행의 검증이 아니다. 사고 세부 사용량이 있는 합성 스트림에서도 전체 `output_tokens`를 사용하며 사고 토큰을 또 더하거나 별도 예산을 만들지 않는 회귀를 확인한다. 실제 공급자 집계의 완전성은 확인하지 않았다.

## 설치본 정적 분석과 재현

설치된2.1.310 파일의 크기274,068,224바이트와 SHA-256 `ffb64331bc0ee1b69efb7c2c428bd3ab516bc31b75bf60886b356c97c1c25ffd`는 이전 스냅샷과 같다. 실행 파일이나 추출한 코드를 저장소에 복제하지 않는다. 다음은 embedded JavaScript를 읽어 해석한 결과이며 **실행 관측이나 완전한 제어 흐름 증명은 아니다**.

- `output_limit_resolution`·`main_request_cap`·`wire_max_tokens`: 환경변수의 유효값을 모델 상한으로 낮추고, 주 요청의 override와 상한 중 작은 값을 `max_tokens`에 넣는 코드를 확인했다. 동적 모델 정보·원격 설정·다른 내부 요청 전체까지 적용됐다는 증거는 없다.
- `reported_usage_accounting`: `output_tokens`는 전체 출력에 더하고 `output_tokens_details.thinking_tokens`는 별도 사고 세부 집계에 더한다. 사고를 전체 출력에 한 번 더 더하는 코드는 아니다. 공급자가 실제로 포함해 보고했다는 관측은 없다.
- `api_retry_limit`: 명시된 재시도 값은0 이상이면 사용한다. 기본 오류 재시도를0으로 요청할 정적 근거다.
- `structured_output_attempts`: print 검증 루프가 설정과 누적 시도를 비교하고 `error_max_structured_output_retries`로 종료하는 분기를 확인했다.
- `nonstreaming_fallback_switch`·`separate_stream_recovery`: fallback 차단값을 읽는 분기와별개의 사고만 생성한 응답·잘린 스트림 복구 카운터가 공존한다. 세 설정을 전체 내부 재호출 차단으로 승격하지 않는다.

각 이름의0기준 byte offset·길이·조각 SHA-256은 [스냅샷](claude-output-limit-support.json)의 `cli_static_evidence.fragments`가 기준이다. 읽기 전용 재현은 다음과 같으며 CLI를 실행하지 않는다.

```sh
python3 ~/.agents/tools/agent_workflow.py check -- python3 - <<'PY'
import hashlib, json, shutil
from pathlib import Path
evidence = json.loads(Path('docs/research/claude-output-limit-support.json').read_bytes())
binary = Path(shutil.which('claude')).resolve().read_bytes()
assert len(binary) == evidence['cli_bytes']
assert hashlib.sha256(binary).hexdigest() == evidence['cli_sha256']
for fragment in evidence['cli_static_evidence']['fragments']:
    start, size = fragment['offset'], fragment['length']
    assert hashlib.sha256(binary[start:start+size]).hexdigest() == fragment['sha256']
print('installed binary and static fragment hashes match; no CLI invocation')
PY
```

## 남은 근거와 조사 한계

- OAuth 구독 요청에서 실제 적용된8192 및 사고+응답의 동일 집계: 설치 버전·모델·인증·두 출력 경로를 명시한 공급자 지원 계약이나, 향후 별도 허가를 받은 최소 요청/응답 메타데이터 근거가 필요하다. 현재 공급자 관측은 없어 미확인이다.
- 내부 재호출 전체 통제: 출력 상한·사고만 생성·잘린 스트림·연결/인증 복구 등 각 분기의 요청 전 입장 차단과 상한 전달을 보장하는 공식 제어·지원 계약 또는 검토 가능한 전체 경로 근거가 필요하다. 이벤트를 받은 뒤 중단한 사실만으로 추가 요청이 시작되지 않았다고 증명할 수 없다.
- 출력 상한 복구 전용 disable 변수·CLI 옵션: 조사한 env-vars·CLI reference 및 공식 변경 이력에서 계약을 찾지 못했다. 전체 기능의 부존재를 단정하지 않는다.
- `settings` 본문과 우선순위는 읽었지만 연결된 `settings-reference` 전체는 공개 문서 도구의 4 MiB 크기 제한으로 열리지 않았다. 공식 Markdown 경로의 직접 읽기도 HTTP 403으로 실패했다. 따라서 모든 settings key를 전수 조사했다는 결론은 내리지 않는다. [All settings](https://code.claude.com/docs/en/settings-reference)
- 번역본·커뮤니티 이슈·비공식 소스 재구성 자료는 현재 동작의 근거로 사용하지 않았다. 문서 상태는 확인일의 스냅샷이다.

생략·미검사: 설치 CLI 실행, 실제 모델/평가 호출, 계정·키·세션·과거 평가 원문 접근은 하지 않았다.
남은 위험: 이 문서와 오프라인 설정 전파 검사만으로 구독 공급자의 실제 1회 응답·각 응답8192 상한 준수를 입증할 수 없다.

준비 상태와 #285/#111/#47은 미완료로 유지한다. 실제 평가 freeze/run과 모델 호출은 계속 보류한다.

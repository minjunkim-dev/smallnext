# Claude Code 출력 제한·내부 재시도 공식 근거 조사

확인일: 2026-10-25 KST. 대상: Smallnext #285 후속 조사, Claude Code 구독 OAuth, `claude-haiku-5-5`, `xhigh`, `-p --output-format stream-json --verbose --include-partial-messages --max-turns 1`, 애플리케이션의 `structured`·`text-json` 경로.

공개 공식 문서·공식 저장소 변경 이력과 설치본의 제한한 정적 바이트 범위를 조사했다. 이번 확인에서 설치 CLI를 실행하거나 계정·키·세션·과거 평가 원문을 읽지 않았다. 실제 모델 호출, 평가 freeze/run, 유료 API 사용, 키 생성은 수행하지 않았다. 공급자 요청·응답 관측은 없다. 설치본 식별자·분석 범위·해시는 [지원 근거 스냅샷](claude-output-limit-support.json)에 기록했다.

## 결론

8192 설정의 문서 근거는 확인되지만 대상 OAuth의 모든 내부 경로 적용을 증명하지는 못한다. 구독의 실제 상한·사고 집계·역할당 응답 1회는 **미확인**이다. [Claude Code 환경변수](https://code.claude.com/docs/en/env-vars)

문서로 식별되는 오류 재시도·스키마 검증 시도 제한은 오프라인 보완의 근거가 된다. 아래 #295 조사에서 일반 스트림 가드와 별도 복구 경로를 연결했지만, 전체 전송 경로의 차단은 입증하지 못했다. 공식 변경 이력은 출력 상한 뒤 자동 이어쓰기가 존재함을 명시한다. [Claude Code 공식 CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md#210)

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
| `CLAUDE_CODE_NONSTREAMING_TIMEOUT_RETRIES` | 비스트리밍 요청의 timeout 재전송 횟수. 0이면 첫 timeout에서 실패하며 2.1.285 이상이 필요하다. | #295에서 별도 재전송 경로에 0을 고정. 최초 fallback 진입을 막는 설정은 아님. |
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

기존 자식 환경에 `CLAUDE_CODE_MAX_RETRIES=0`, `MAX_STRUCTURED_OUTPUT_RETRIES=1`, `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1`을 고정했다. #295에서는 `CLAUDE_CODE_NONSTREAMING_TIMEOUT_RETRIES=0`도 고정했다. 부모의 큰 재시도 값이나 watchdog는 상속하지 않는다. 기존8192·구독 강제·모델/effort·설정 출처 차단·도구/hooks/MCP 차단을 유지한다.

생성·검사와 두 출력 경로에서 가짜 CLI가 받은 값 및 정상 결과·오류 뒤 회수를 검증한다. 이는 가짜 프로세스의 전달 검증이며 실제 CLI 내부 실행의 검증이 아니다. 사고 세부 사용량이 있는 합성 스트림에서도 전체 `output_tokens`를 사용하며 사고 토큰을 또 더하거나 별도 예산을 만들지 않는 회귀를 확인한다. 실제 공급자 집계의 완전성은 확인하지 않았다.

## 설치본 정적 분석과 재현

설치된2.1.310 파일의 크기274,068,224바이트와 SHA-256 `ffb64331bc0ee1b69efb7c2c428bd3ab516bc31b75bf60886b356c97c1c25ffd`는 이전 스냅샷과 같다. 실행 파일이나 추출한 코드를 저장소에 복제하지 않는다. 다음은 embedded JavaScript를 읽어 해석한 결과이며 **실행 관측이나 완전한 제어 흐름 증명은 아니다**.

- `output_limit_resolution`·`main_request_cap`·`wire_max_tokens`: 환경변수의 유효값을 모델 상한으로 낮추고, 주 요청의 override와 상한 중 작은 값을 `max_tokens`에 넣는 코드를 확인했다. 동적 모델 정보·원격 설정·다른 내부 요청 전체까지 적용됐다는 증거는 없다.
- `reported_usage_accounting`: `output_tokens`는 전체 출력에 더하고 `output_tokens_details.thinking_tokens`는 별도 사고 세부 집계에 더한다. 사고를 전체 출력에 한 번 더 더하는 코드는 아니다. 공급자가 실제로 포함해 보고했다는 관측은 없다.
- `api_retry_limit`: 명시된 재시도 값은0 이상이면 사용한다. 기본 오류 재시도를0으로 요청할 정적 근거다.
- `structured_output_attempts`: print 검증 루프가 설정과 누적 시도를 비교하고 `error_max_structured_output_retries`로 종료하는 분기를 확인했다.
- `nonstreaming_fallback_switch`·`separate_stream_recovery`: fallback 차단값을 읽는 분기와별개의 사고만 생성한 응답·잘린 스트림 복구 카운터가 공존한다. 이 설정들을 전체 내부 재호출 차단으로 승격하지 않는다. #295의 후속 경로 표를 함께 읽는다.

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

## #295 분기별 요청 전 차단 조사

이 절은 같은 설치본의 정적 읽기 결과다. 실행이나 계정 관측이 아니다. 아래 식별자는 지원 JSON의 `cli_static_evidence.fragments`에 추가했고 기존8조각은 보존했다. 해시 재현은 위 명령으로 이 절의21조각과 #296 추가14조각을 검사한다. 함수명은 이 설치본 안의 지역 이름이며 공개 API가 아니다. 조각 간 연결은 아래에 명시한 범위만 확인했다. 이름이 같은 다른 모듈을 연결하거나 전체 호출 그래프를 복원했다고 주장하지 않는다.

### 전송점과 가드 연결

- **일반 API 오류:** `api_retry_limit`의 `Ket` → `retry_budget_options`의 `FLe` → `Ukn` → `stream_retry_options`의 남은 재시도 → `request_retry_entry`의 `cRe` 순으로 연결된다. SDK client 자체의 `maxRetries`는0이고, `cRe`가 별도 루프에서 `stream_request_send`의 `beta.messages.create` 콜백을 호출한다. 일반 경로는 `Gn <= h+1` / `Gn > h` 가드를 거쳐0에서 첫 실패로 끝난다. **단, 오류 수정·인증 등 아래 예외를 거치지 않았다는 조건에서만** 이 가드가 적용된다.
- **오류 수정·인증 예외:** `request_error_repair`는 `onError`가 새로운 수정 키를 반환하면 `Gn--` 뒤 루프에 재진입한다. `stream_retry_options`는 실제 오류 수정 콜백을 전달한다. 따라서 일반 횟수 가드보다 앞의 수정 경로를 재시도0으로 차단했다고 볼 수 없다. `credential_retry_guard`도 인증 조건과 별도 갱신 허용량을 확인하고 카운터를 되돌린다. `retry_ledger`의 갱신 허용량과 총 API 시도 ledger는 별개다. OAuth 갱신 자체는 생성 요청이 아니지만, `request_retry_entry`의 갱신/클라이언트 재구성 뒤 콜백 재호출은 생성 재전송 가능 경로다. 실제 OAuth 조건 판정·서버 오류 분류·모든 수정 키의 도달 여부는 미추적이다.
- **스트림 복구:** `stream_recovery_policy`에서 thinking-only/truncation/stall 등의 일부 분기는 `YH` → `yL`의 `retries < maxRetries` 가드로 연결된다. `thinking_stream_reentry`에서는 분류 결과가 retry이면 바깥 스트림 루프에 재진입한다. 일반 가드0에서 해당 retry 결정은 막히지만, `stream_error_repair`의 오류 수정 후 카운터 복원·재진입과 모델 fallback 등은 별도다. 모든 원인·진행 상태 조합을 차단했다고 보고하지 않는다.
- **비스트리밍 전환:** `nonstreaming_fallback_switch`의 차단값은 중간 스트림 실패 분류에 전달된다. 반면 `stream_recovery_policy`의 HTTP404 처리 → `retry_ledger.onWithRetryGaveUp` → `nonstreaming_404_entry`는 별도 `X_t` 진입이다. 이 진입 위치에서는 중간 스트림 fallback 차단값을 다시 검사하지 않는다. `X_t`의 모든 전송 하위 경로와 실제404 도달 여부는 미추적이다. 최초 전환과 전환 후 timeout 재전송은 다르다.
- **비스트리밍 timeout:** `request_error_repair`의 timeout 분기는 공식 `CLAUDE_CODE_NONSTREAMING_TIMEOUT_RETRIES`와 누적값을 먼저 비교한다. 0이면 첫 timeout에서 예외로 끝내는 정적 근거가 있다. #295는 이 변수0을 자식 환경에 추가하고 부모99를 덮어쓰는 가짜 CLI 전달을 검증한다. 이 보완은404 최초 전환이나 다른 오류 수정을 막는 증거가 아니다.
- **출력 상한·상위 이어쓰기:** `output_recovery_configuration`은 기본 복구 상한3과 원격 설정 해석을 가진다. `output_recovery_transition`은 `max_output_tokens_recovery` 또는 `truncated_response_recovery` 상태를 만들고 반환한다. 이 조각에는 위 오류 재시도·schema 횟수·fallback 차단값을 검사하는 가드가 없다. 다음 상태에서 새 모델 호출로 돌아가는 전체 dispatcher 간선, print의 turn 제한과의 순서, 두 출력 방식의 실제 도달 여부는 미추적이다. 원격 내부 키를 사용자용 disable 옵션으로 사용하지 않는다.
- **schema 검증:** `structured_output_attempts`는 print 루프의 특정 user 상태와 schema 조건에서 누적 시도를 비교하고, 유효 출력이 없으면 종료 결과를 내보낸 뒤 반환한다. 총1시도 가드는 그 분기에 적용된다. 완료 출력의 모델 fallback 철회가 이 비교를 언제 거치는지와 상위 복구보다 앞서 종료되는지는 미추적이다. schema가 없는 `text-json`에는 이 가드로 전체 요청 수를 증명하지 않는다. 공식 SDK도 철회 후 유효 출력 부재를 오류에 포함한다. [구조화 출력 오류](https://code.claude.com/docs/en/agent-sdk/structured-outputs#error-handling)

공통 `stream_retry_options` → `stream_request_send`의 주 요청은 기존 `main_request_cap` → `wire_max_tokens`와 연결된다. 그러나 다른 모델·비스트리밍·상위 복구의 상한 전달까지 전수 확인하지 않았다. 그 적용·예외는 아래 #296 조사에서 일부 보완했으며8192 보장을 해소하지 않는다. optional `apiAttemptsLeft` ledger는 존재하지만 print 경로에서 역할당1로 초기화되고 모든 하위 요청에 전파된다는 근거가 없다. 공개된 역할당 요청 수 옵션으로 취급하지 않는다.

### G/C와 출력 방식별 적용 표

`적용`은 해당 **부분 가드**를 정적으로 연결했다는 뜻이며 전체 요청 전 차단 성공을 뜻하지 않는다. `미추적`은 가드 예외·도달 조건·다음 전송 간선 중 일부가 남은 상태다. `비적용`은 schema가 없는 경로에 schema 가드를 사용하지 않는다는 뜻이다. G와 C는 같은 호출 어댑터지만 prompt/schema가 다르며 실제 동등성을 관측하지 않았다. 모든 칸은 실행 결과가 아니다.

| 분기·검사 대상 | G structured | C structured | G text-json | C text-json | 근거 식별자·남은 간선 |
| --- | --- | --- | --- | --- | --- |
| 일반 API 오류·429/529·연결 실패의 횟수 가드 | 적용 | 적용 | 적용 | 적용 | `api_retry_limit`, `retry_budget_options`, `stream_retry_options`, `request_retry_entry`; 수정·인증·capacity 예외는 다음 행 |
| 오류 수정·capacity 대기·인증 후 생성 재전송 | 미추적 | 미추적 | 미추적 | 미추적 | `request_error_repair`, `credential_retry_guard`, `retry_ledger`; 실제 오류 분류·계정/원격 조건과 모든 예외 미추적 |
| schema 실패의 총1시도 가드 | 적용 | 적용 | 비적용 | 비적용 | `structured_output_attempts`; 특정 print 상태에서 종료, 전체 선행 경로는 미추적 |
| 모델 fallback의 완료 출력 철회 | 미추적 | 미추적 | 비적용 | 비적용 | schema 없는 칸은 schema 출력 철회에 비적용; 모델 전환 자체는 아래 별도 행 |
| max_tokens 뒤 상위 자동 이어쓰기 | 미추적 | 미추적 | 미추적 | 미추적 | `output_recovery_configuration`, `output_recovery_transition`; 다음 dispatcher·turn 순서 미추적 |
| thinking-only의 일반 스트림 재시도 가드 | 적용 | 적용 | 적용 | 적용 | `stream_recovery_policy`, `thinking_stream_reentry`; 수정/인증·상위 복구는 보장 밖 |
| 잘린 스트림의 일반 재시도 가드 | 적용 | 적용 | 적용 | 적용 | `stream_recovery_policy`; 상위 `truncated_response_recovery`는 미추적 |
| 중간 스트림 실패의 nonstreaming 차단 가드 | 적용 | 적용 | 적용 | 적용 | `nonstreaming_fallback_switch`; 오류는 retry layer로 전달됨 |
| HTTP404 뒤 최초 nonstreaming 진입 | 미추적 | 미추적 | 미추적 | 미추적 | `stream_recovery_policy`, `retry_ledger`, `nonstreaming_404_entry`; `X_t` 이하 전수 미추적 |
| nonstreaming timeout 재전송0 가드 | 적용 | 적용 | 적용 | 적용 | `request_error_repair`; 도달 여부를 실행으로 확인한 것은 아님 |
| 모델 자동 fallback·호출 재시작 | 미추적 | 미추적 | 미추적 | 미추적 | `stream_recovery_policy`, `thinking_stream_reentry`; 모델 선택/상위 catch·재전송 연결 미추적 |
| 관리 정책·원격 설정에 따른 우회/재정의 | 미추적 | 미추적 | 미추적 | 미추적 | `output_recovery_configuration`, `retry_budget_options`; 계정·관리/원격 상태를 읽지 않음 |

### 공급자 질문 초안과 필요한 답변

아래는 [#298](https://github.com/minjunkim-dev/smallnext/issues/298)에 넘길 질문 초안이다. 발송하거나 호출하지 않았다. 대상은 이 문서 첫머리의 구독 OAuth·설치 SHA·모델/effort·G/C·두 애플리케이션 방식이다. 동일 CLI `stream-json`이라는 점도 함께 명시해야 한다.

1. 네 고정값(API 오류 재시도0, schema 총1, 중간 스트림 fallback 차단1, 비스트리밍 timeout 재전송0)과 `--max-turns 1`에서 **최초 생성 요청 뒤 모든 추가 생성 요청을 전송 전에 거부하는 공식 지원 제어**가 있는가? 있다면 최소 버전·정확한 옵션·우선순위·적용 범위와 오류/종료 결과를 문서로 제공해 달라. 네 값의 조합을 그 보장으로 인정할 수 없다면 지원 불가/예외를 명시해 달라.
2. 오류 수정/헤더 재구성,429/529·capacity 대기·연결 복구, OAuth401 갱신 뒤 재전송, 모델 fallback,404 비스트리밍 진입 각각에서 위 횟수 가드를 우회하는가? 인증 갱신 요청과 생성 재전송을 나누고, 전송 전 차단 위치와 opt-in 없는 자동 재전송의 예외를 설명해 달라.
3. max_tokens·thinking-only·truncation의 상위 복구/이어쓰기를 각각 끄는 지원 방법이 있는가? schema 검증/완료 출력 철회와 agentic turn 제한보다 어떤 순서로 실행되며, 관리 정책·원격 설정으로 동작이 달라질 수 있는가?
4. 지원한다면 모든 하위 전송을 포함하는 역할당 최초1/추가0 ledger의 범위와, 요청ID에 연결된 생성 요청 수·실제 적용 모델/8192·완료/누락 상태를 어떤 **공식 메타데이터 경로**로 확인할 수 있는가? 내부 ledger나 사후 이벤트만으로 전송 전 차단을 입증할 수 없다면 그 한계도 명시해 달라.

필요한 답변은 대상 인증·버전·모델·출력 방식과 예외가 명시된 공식 문서/지원 답변 또는 검토 가능한 전체 경로 근거다. 일반 API 설명·문의 접수·짧은 정상 응답 몇 건은 충분하지 않다. 답변이 없거나 지원 불가이면 미확인을 유지한다. 질문에 원문 입력/출력·사고 텍스트·계정/자격 증명·vendor 추출 코드는 필요 없다.

#295의 오프라인 조사는 이 표와 질문 정리로 완료할 수 있지만, 준비 상태나 실관측 승인으로 이어지지 않는다. [#299](https://github.com/minjunkim-dev/smallnext/issues/299)는 전송 전 통제와 관측 경로가 불명확한 동안 승인 요청 준비 상태로도 올리지 않는다. 하네스의 추가 메시지/재시도 이벤트 감지와 프로세스 회수는 사후 방어이며 이미 시작된 추가 요청0회 증거가 아니다.

## #296 응답별8192 경로·예외 조사

대상·설치 SHA·확인일은 첫머리와 같다. 기존21조각을 보존하고14조각을 추가했다. 아래 식별자는 지원 JSON의 offset·길이·해시로 재현한다. 표의 연결은 제한한 정적 코드 해석이며, 실행한 CLI·공급자 요청을 관측한 결과가 아니다. G/C는 같은 `call` 어댑터를 쓰며 prompt/schema만 다르다. 요청한 모델/인증과 실제 적용된 값을 구분한다.

### 설정 선택에서 전송까지

| 단계 | 확인한 경로 | 미확인·예외 |
| --- | --- | --- |
| 자식 경계 | `environment()`의 허용 목록 후 고정8192, `_call`의 `--setting-sources ''`, inline `forcedLoginMethod=claudeai`, 고정 모델/effort. 기존 가짜 CLI 검사에서 G/C×두 방식의 부모 미설정/65536/invalid를8192로 덮어씀 | 가짜 프로세스가 받은 환경·인수만 증명. CLI가 실제로 읽은 최종 설정이나 계정 인증을 관측하지 않음 |
| 공식 우선순위 | `--setting-sources`는 user/project/local 선택이며 inline `--settings`는 managed 아래다. 환경변수와 전용 key 우선순위는 쌍마다 다르고 settings `env`도 설정 우선순위를 따름 | 설정 출처 빈 값으로 managed까지 껐다고 판단하지 않음. 사용자/관리 설정을 읽지 않았으며 최종 env의 값은 미확인. [설정 우선순위](https://code.claude.com/docs/en/settings#settings-precedence), [CLI](https://code.claude.com/docs/en/cli-reference) |
| 모델별 default/ceiling | 기존 `output_limit_resolution`: `kue`가 모델 식별·상한/descriptor·동적 기본값·모델 metadata를 선택. `output_cap_dynamic_default`는 양의 정수 기본값 선택, `output_cap_model_metadata`는 모델 목록에서 일치/부분일치 metadata 선택 | 모델 정보·캐시/원격 입력의 실제 값과 공급자별 일치가 미확인. 이 값은 공개 사용자용 override 옵션으로 취급하지 않음 |
| env parse/clamp | `output_cap_parse`의 `Mzt`: 값 없음/invalid/0 이하는 default, ceiling 초과는 ceiling, 나머지는 양수값. `pvt`는 고정 env를 이 계산에 전달 | 유효8192와 정상 ceiling이면 결과는8192 이하. invalid에서 실패 종료하지 않고 default로 복귀하므로 부모값 차단만으로 CLI 내부 fallback까지 실패 차단했다고 볼 수 없음. 실제 parser의 모든 문자열을 모의 재구현하지 않음 |
| 모델 정보 선택 | `model_facts_output_cap`: `_c`가 `maxOutputTokens:pvt(e)`를 구성. `request_model_facts_choice`: 모델이 일치하는 전달 `modelFacts`를 재사용하거나 `_c(pt)`로 계산 | 전달 modelFacts의 생성/갱신 시점·원격 조건과 모든 caller를 전수 추적하지 않음. 현재 env로 매 전송 직전 재계산한다고 단정하지 않음 |
| 요청 override와 사고 | 기존 `main_request_cap`: retry `maxTokensOverride`, 요청 `maxOutputTokensOverride`, descriptor 값 중 선택한 값을 descriptor와 `min`. 고정 사고 예산은 `min(JT-1,budget)` 뒤 최소1024 적용, adaptive는 별도 고정 사고 예산을 만들지 않음 | descriptor가8192 이하면 이 `min` 자체는 늘리지 않음. 모델/descriptor 변경과 이후 body 병합까지 보장하는 최종 cap은 아님. 구독의 사고 포함 계약은 #297 미확인 |
| 후순위 body·stream | `request_body_builder`의 `ELe→xeo`가 `i2`를 읽음. `request_extra_body`는 `CLAUDE_CODE_EXTRA_BODY` JSON 객체를 가져오고 `request_body_merge`는 계산한 `max_tokens` 뒤에 이 객체를 spread함. 기존 `stream_request_send`에서 `pcn` 후 `beta.messages.create(stream:true)` | extra body에 `max_tokens`가 있으면 앞 계산을 덮어쓸 수 있는 정적 순서. 다른 후순위 spread 전체의 입력은 미추적. `request_wire_transform`의 `pcn`은 도구/메시지 변환이며 이 조각에서 cap을 다시 적용하지 않음. SDK 내부 직렬화·네트워크·서버는 관측 안 함 |
| nonstreaming 전환 | `nonstreaming_shared_builder`: `X_t`가 `j_r`에 같은 `ELe` 전달. `nonstreaming_cap_send`: builder 결과를 `bkr`로 낮춘 뒤 `pcn`·`beta.messages.create(stream:false)`. `nonstreaming_cap_clamp`: body cap과 별도 상수의 `min`, 고정 사고 budget도 재조정 | 입력 body가8192 이하면 이 `min`은 증액하지 않음. 입력이 이미 후순위 override된 경우8192 복구 보장은 아님. #295의404 진입과 timeout 재전송0은 전환/횟수 제어로서 cap 보장과 별개 |
| 상위 복구·재호출 | `upper_recovery_cap_reset`는 transition 없을 때만 요청 override를 재사용하고 transition이면 제거. `upper_recovery_cap_argument`는 그 값을 다음 호출 옵션에 전달 | override 제거가 고정8192의 해제라는 뜻은 아니지만, 다음 descriptor/모델/body 재구축·dispatcher의 모든 간선은 미추적. #295의 recovery 상태와 결합해도 모든 추가 전송 cap/횟수 보장은 아님 |

공식 env 문구는 **대부분 요청**의 cap이다. 이를 대상 OAuth의 모든 최초·복구 요청에 확장하지 않는다. 일반 API의 `max_tokens`는 사고+텍스트를 합친 요청당 한도이며, 각 재요청은 별도 한도다. API 문서의128K ceiling·xhigh 설명은 구독에서8192가 실제 적용됐다는 증거가 아니다. [환경변수](https://code.claude.com/docs/en/env-vars), [API 사고·출력 한도](https://platform.claude.com/docs/en/build-with-claude/thinking#output-limits), [요청별 비용 제어](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost#cost-control)

### #295 분기와 G/C·두 출력 방식의 대응

`부분`은 위 builder·clamp의 일부 간선을 연결했다는 뜻이다. `미추적`은 최종 body/도달/재계산/전송 중 빠진 간선이 있다는 뜻이다. **어느 칸도 실제8192 적용 통과가 아니다.** schema 없는 칸도 상한 조사 대상이며 schema 횟수 가드로 cap을 증명하지 않는다.

| #295 분기·최초 요청 | G structured | C structured | G text-json | C text-json | 상한 근거·남은 간선 |
| --- | --- | --- | --- | --- | --- |
| 최초 주 stream 요청 | 부분 | 부분 | 부분 | 부분 | parse→facts→min→body→send; managed/modelFacts/후순위 body는 미확인 |
| 일반 API 오류·429/529·연결 실패 | 부분 | 부분 | 부분 | 부분 | retry 콜백이 `ELe`를 다시 호출; 수정·인증/capacity 예외 전체는 미추적 |
| 오류 수정·capacity·인증 뒤 생성 재전송 | 미추적 | 미추적 | 미추적 | 미추적 | #295 `request_error_repair`, `credential_retry_guard`; 수정 키별 body/모델 변화 미추적 |
| schema 실패의 총1시도 | 미추적 | 미추적 | 비적용 | 비적용 | `structured_output_attempts`의 종료는 cap 증거가 아님; 우회/선행 호출 미추적 |
| 모델 fallback의 완료 출력 철회 | 미추적 | 미추적 | 비적용 | 비적용 | 철회 자체는 schema 경로; 재요청은 모델 전환 행 |
| max_tokens 뒤 상위 이어쓰기 | 미추적 | 미추적 | 미추적 | 미추적 | `output_recovery_transition`, override reset/argument; 전체 재구축 미추적 |
| thinking-only의 일반 stream 재시도 | 부분 | 부분 | 부분 | 부분 | 주 builder를 재사용하는 일반 경로만; 다른 상위 복구 미추적 |
| 잘린 stream의 일반 재시도 | 부분 | 부분 | 부분 | 부분 | 일반 재진입만; 상위 truncation 복구 미추적 |
| 중간 stream 실패의 nonstreaming 차단 | 부분 | 부분 | 부분 | 부분 | 차단 분기는 #295; 전환 시 공유 builder→nonstream min→send만 연결 |
| HTTP404 뒤 최초 nonstreaming | 부분 | 부분 | 부분 | 부분 | `nonstreaming_404_entry`→shared builder→cap/send; 후순위 body/실제 도달은 미확인 |
| nonstreaming timeout 재전송 | 부분 | 부분 | 부분 | 부분 | #295 timeout0 가드와 같은 builder; 다른 오류 예외는 미추적 |
| 모델 자동 fallback·호출 재시작 | 미추적 | 미추적 | 미추적 | 미추적 | 모델별 descriptor·effort·env/body 재구축 전수 미추적 |
| 관리 정책·원격 설정의 재정의 | 미추적 | 미추적 | 미추적 | 미추적 | managed/env/modelFacts/원격 복구 실제 입력은 읽거나 실행하지 않음 |

### 보완과 판정 기준

현재 자식 환경 허용 목록은 부모의 `CLAUDE_CODE_EXTRA_BODY`를 이미 제외한다. 이 티켓에서는 기존 가짜 CLI 경계에 부모의 `max_tokens:65536`·다른 모델을 가진 합성 extra body를 넣고 G/C×두 방식 모두 자식에 전달되지 않음을 확인한다. 기존 미설정/큰값/invalid cap 변형도 함께 유지한다. CLI 내부 설정 적용을 흉내 낸 새 하네스나 중복 cap 설정은 추가하지 않았다. production 동작의 새 결함을 재현하지 않았으므로 동작 변경 없이 근거 JSON과 pin/source 호환 hash만 갱신한다. 기존 역사 hash는 보존한다.

| 증거 종류 | 충족 판정 | 현재 상태·미충족 처리 |
| --- | --- | --- |
| 공식 계약 | 정확한 OAuth·CLI 버전·모델/effort·G/C·두 방식과 최초/모든 복구 예외의 응답별8192·사고 포함 범위를 명시 | 대부분 요청/일반 API 설명만으로 불충족 |
| 정적 경로 | 설정 선택부터 모든 전송의 최종 body·override·원격/모델 예외까지 추적 가능 |35조각의 제한한 경로만 확인. 동적 입력/간선이 남아 불충족 |
| 모의 전달 | 기존 fake CLI가 고정8192와 격리 인수를 수신하고 부모 extra body가 없음 | 전달 경계만 충족. 실제 CLI/공급자 cap 검증으로 승격 안 함 |
| 향후 별도 승인 관측 | 지원되는 공식 경로로 요청ID와 결합한 요청값·실제 적용값·응답/누락 상태를 대조 | 미실행. 짧은 응답·문자/byte 길이·123역할 합산·몇 건 정상 종료는 보장 증거 아님 |

### 공급자 질문·최소 메타데이터·확보 채널

[#298](https://github.com/minjunkim-dev/smallnext/issues/298)에 넘길 **초안**이며 발송 승인은 아니다. 대상 식별자는 첫머리의 계약과 설치 SHA를 사용하고, 내부 vendor 코드나 offset 원문을 문의에 첨부하지 않는다.

1. 이 OAuth 구독/CLI2.1.310/Haiku5.5/xhigh의 G/C×schema 있음/없음(둘 다 stream-json)에서 환경8192가 **모든 응답의 사고+텍스트 합계**에 적용되는 공식 계약인가? 대부분 요청에서 제외되는 종류, 최소 버전, 우선순위, 관리/원격 정책 예외, 미지원/값 누락 시 종료 동작을 명시해 달라.
2. 전달된 모델 정보·요청 override·후순위 extra body·모델 전환·오류 수정/인증·404/nonstreaming·상위 max_tokens/thinking-only/truncation 복구 각각에 cap이 다시 적용되는 위치와 지원되는 고정 방법은 무엇인가? 기본값 복귀나 증액 가능한 예외와 요청 전 거부 방법도 설명해 달라. 횟수0 가드와 응답별 cap 계약을 구분해 달라.
3. payload 없이 확인할 **요청ID 결합 공식 메타데이터 경로**가 있는가? 클라이언트가 요청한 `max_tokens`와 공급자가 실제 적용한 cap·사고 포함 여부를 별도 필드로 확인할 수 있는지, 필드 미제공/취소/미완료에서는 무엇을 미확인으로 남겨야 하는지 알려 달라.

| 최소 필드 | 필요한 구분·확보 경로 |
| --- | --- |
| CLI 버전/SHA, 요청 역할·방식·최초/복구 분기 식별자 | 현재 정적/모의 근거. 향후 승인된 실행에서는 같은 계약 식별자로 연결 |
| 인증 종류(비밀값 제외), 요청/실제 적용 model·effort | 공식 문서/지원 답변에서 대상 범위 확인. 실제 값은 공급자가 지원하는 metadata에 있을 때만 기록 |
| 요청 `max_tokens`, 공급자 적용 cap, 사고 포함 규칙 | 요청값/적용값을 구분. 서버 필드가 없으면 env/요청값으로 대체하지 않음 |
| request ID, response/message ID, 생성 요청 순번·완료/누락 상태 | 지원되는 request/response header 또는 비식별 이벤트/지원 조회 경로가 존재하는지 먼저 공식 확인. 임의 필드·API endpoint를 만들지 않음 |
| stop reason, reported total output tokens 및 완전성/취소 상태 | 한도 도달·추가 요청·누락을 성공으로 보정하지 않음. 사용량의 집계 계약은 #297과 연결 |

공개 공식 문서의 명시된 범위를 우선 사용한다. 부족할 때의 후보 채널은 [공식 지원 안내](https://support.claude.com/en/articles/9015913-how-to-get-support)의 Claude 계정 메뉴 `Get help` → support messenger → `Send us a message`다. Fin이 필요한 조사를 Product Support로 넘기고 같은 대화/계정 이메일로 답변한다는 공개 절차만 확인했으며, 로그인하거나 messenger를 열지 않았다. 정확한 수신 경로·최종 문안·공유 범위는 #298에서 별도 사용자 승인을 받거나 사용자가 직접 발송한다. 비공식 이슈 답변·접수 확인·일반 API 설명만으로 닫지 않는다. payload·입출력 원문·사고 텍스트·서명·토큰·쿠키·계정 식별자는 필요 없다. 공식 metadata 경로가 없으면 TLS 가로채기/프록시/CLI 패치로 우회하지 않고 미확인을 유지한다. 이 표는 관측 schema 요구이며 필드가 현재 CLI에 존재한다는 주장이 아니다.

#296의 오프라인 조사 종료는 `subscription_model_output_cap_unverified` 해소가 아니다. 세 미확인과 `ready=False`, #285/#111/#47 OPEN을 유지한다. #297 사고 집계 조사·#298 문의 발송 승인·#299 실관측 필요성/별도 승인과 구분하며, 실제 평가 freeze/run·모델 호출·문의 발송은 계속 보류한다.

## 남은 근거와 조사 한계

- OAuth 구독 요청에서 실제 적용된8192 및 사고+응답의 동일 집계: 설치 버전·모델·인증·두 출력 경로를 명시한 공급자 지원 계약이나, 향후 별도 허가를 받은 최소 요청/응답 메타데이터 근거가 필요하다. 현재 공급자 관측은 없어 미확인이다.
- 내부 재호출 전체 통제: 출력 상한·사고만 생성·잘린 스트림·연결/인증 복구 등 각 분기의 요청 전 입장 차단과 상한 전달을 보장하는 공식 제어·지원 계약 또는 검토 가능한 전체 경로 근거가 필요하다. 이벤트를 받은 뒤 중단한 사실만으로 추가 요청이 시작되지 않았다고 증명할 수 없다.
- 출력 상한 복구 전용 disable 변수·CLI 옵션: 조사한 env-vars·CLI reference 및 공식 변경 이력에서 계약을 찾지 못했다. 전체 기능의 부존재를 단정하지 않는다.
- `settings` 본문과 우선순위는 읽었지만 연결된 `settings-reference` 전체는 공개 문서 도구의 4 MiB 크기 제한으로 열리지 않았다. 공식 Markdown 경로의 직접 읽기도 HTTP 403으로 실패했다. #296에서 공식 색인의 해당 Markdown 경로와 본문/anchor를 정상 GET으로 재확인했지만 같은 크기 제한/403으로 전체 key를 읽지 못했다. 따라서 모든 settings key를 전수 조사했다는 결론은 내리지 않는다. [All settings](https://code.claude.com/docs/en/settings-reference)
- 번역본·커뮤니티 이슈·비공식 소스 재구성 자료는 현재 동작의 근거로 사용하지 않았다. 문서 상태는 확인일의 스냅샷이다.

생략·미검사: 설치 CLI 실행, 실제 모델/평가 호출, 계정·키·세션·과거 평가 원문 접근은 하지 않았다.
남은 위험: 이 문서와 오프라인 설정 전파 검사만으로 구독 공급자의 실제 1회 응답·각 응답8192 상한 준수를 입증할 수 없다.

준비 상태와 #285/#111/#47은 미완료로 유지한다. 실제 평가 freeze/run과 모델 호출은 계속 보류한다.

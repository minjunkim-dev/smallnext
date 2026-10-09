# 입력량 축소 검사 보정

2026-10-09, [Issue #90](https://github.com/minjunkim-dev/smallnext/issues/90).
생성·별도 의미 검사·실패 시 상태 보존과 자동 재시도 0은 [#40의 확정 답](https://github.com/minjunkim-dev/smallnext/issues/40#issuecomment-5982135283)을 유지합니다.
서버 설정과 출시 경계는 [SERVER_AI](../SERVER_AI.md)가 기준입니다.

## 확인한 문제와 수정

업무 목표의 `더 작게` 후보를 같은 입력으로 검사했을 때 거절과 수용이 바뀌었습니다.
첫 검사는 한 단어의 목차 제목을 같은 작업의 반복과 임시 표시로 해석했습니다.
재검사는 입력 단위 감소와 목표 진전으로 해석했습니다.
과거 시뮬레이터의 거절 후보 원문은 없으므로 과거 세 건의 정확한 이유를 이 재현으로 대체하지 않습니다.

공통 생성·검사 프롬프트를 다음과 같이 보정했습니다.

- 유용한 결과를 보존한 입력량·준비·조작 감소를 축소로 평가합니다.
- 아직 고르지 않은 열린 내용을 준비된 유용한 한 단위로 좁히는 경우는 선택 부담의 감소로 평가합니다.
- 이미 고른 같은 단위를 반복하거나 예상 시간만 줄이는 후보는 축소가 아닙니다.
- 선택적 예시를 필수 문구로 계산하지 않습니다. 선택적 후속 편집을 필수 수정으로 계산하지 않습니다.
- 입력이 반복 시작 실패를 명시하고 실제 막힘을 모르면 첫 막힘 질문이 우선입니다. 보류·미완료·중첩 분할 이력만으로 반복 실패를 추정하지 않습니다.
- need_info는 실제 질문을 action에 넣습니다. 질문을 reason에만 넣은 안내 문구를 수용하지 않습니다.

목표 기여, 관찰 가능한 결과, 모든 수량·시간 제한, 남은 범위·완료 ID·미완료 상태 보존을 계속 검사합니다.
임시 표시와 후보의 자기 설명만으로 수용하지 않습니다.
도구 접근, 모델·추론 강도, 구조화 출력, timeout, 자동 재시도, 피처 플래그를 변경하지 않았습니다.
개발 CLI와 사용자용 서버는 같은 공통 프롬프트를 포함합니다.
사용자용 서버의 기존 반복 막힘 추가 지침도 유지합니다.

## 고정 합성 평가

[고정 후보](fixtures/quantity-reduction-checks.json)의 첫 8개를 처음 두 평가의 실행 전에 고정했습니다.
기대 판정과 사례 ID는 평가 메타데이터입니다. 모델에는 `original_request`와 `candidate`만 전달했습니다.
각 후보를 세 번 독립 검사했습니다. 한 판정을 수용으로 바꾸려는 제품 재시도가 아닙니다.
처음 두 보정 단계의 최대 호출은 각각 24개입니다. 최종 단계는 27개와 참조 수정 후 별도 3개입니다.
호출당 제한은 120초, 동시 실행은 2개입니다.
실제 모델은 모든 완료 응답에서 `claude-haiku-5-5`로 확인했습니다. 추론 강도는 `xhigh`입니다.
기존 Claude Code 구독 OAuth를 사용했습니다. 파일·셸·MCP 도구와 세션 보존을 비활성화했습니다.
일반 API 호출·키 생성·OAuth 토큰 추출은 없습니다.

| 고정 후보 | 기대 판정 | 첫 보정, 3회 | 2차 보정, 3회 |
| --- | --- | --- | --- |
| 열린 목차 항목을 유용한 제목 한 단어로 좁힘 | accept | reject / reject / reject | accept / accept / accept |
| 버튼 제목 assertion 3개를 1개로 줄임 | accept | accept / accept / accept | accept / accept / accept |
| 완료한 첫 목차 다음에 둘째 목차 작성 | accept | accept / accept / accept | accept / accept / accept |
| 이미 고른 같은 한 단어를 반복 | reject | reject / reject / reject | reject / reject / reject |
| 한 단어 제한에서 두 단어 작성 | reject | reject / reject / reject | reject / reject / reject |
| 모르는 과거 역할을 임시 리더로 발명 | reject | reject / reject / reject | reject / reject / reject |
| 반복 시작 실패에서 원인 대신 펜 접촉 제안 | reject | accept / accept / accept | reject / reject / reject |
| 완료 ID와 남은 범위 삭제 | reject | reject / reject / reject | reject / reject / reject |

첫 보정은 기대 판정 18/24와 일치했습니다. 잘못된 차단 3회와 오수용 3회를 기록했습니다.
2차 보정은 24/24와 일치했습니다. 정상 9회 수용과 실패 15회 거절입니다.
이 8개 고정 후보의 SHA-256은 `ffe34a6b1ea68b080d49dfa3464955a97e663bfa55f337a3107ffd74b8e8a0b7`입니다.
2차 검사 프롬프트 SHA-256은 `28e6cf222e612ef9d3ff9180cbf783a7b7162cf1e2444d4d262ac46e9f507f88`입니다.
같은 고정 사례를 기준 보정에 사용했으므로 미사용 사례의 일반화나 전체 품질 통과율이 아닙니다.
이 기대 판정은 합성 기준의 보조 검토입니다. 사람의 전수 품질 승인이나 실제 사용자 시작 증거가 아닙니다.

### 자동 리뷰 후 보정

자동 코드 리뷰는 명시적인 반복 실패 없이 보류·미완료 이력을 반복 실패로 해석하는 경계를 지적했습니다.
생성·검사 양쪽에 명시적 반복 실패 신호를 요구했습니다. 정상 진행 이력에서 이 신호를 추정하지 않게 했습니다.
질문이 필요한 경우 action에 실제 질문을 넣는 경계도 명시했습니다.
기존 8개 후보는 변경하지 않았습니다. 중첩 분할 원본·현재 행동·보류 이력이 있지만 반복 실패를 보고하지 않은 정상 축소 후보를 추가했습니다.
최종 프롬프트에서 기존 8개 후보의 24회 판정은 모두 기대와 일치했습니다.
추가한 중첩 후보는 처음에 보류 행동과 겹쳤습니다. 정상 수용 참조로 분류한 것이 잘못이었습니다.
검사기는 이 후보를 2회 거절했습니다. 1회는 120초 제한을 초과했습니다. 이 결과를 보존했습니다.
보류 행동과 겹치지 않는 정상 중첩 후보를 별도로 고정했습니다. 세 번 모두 수용했습니다.
최종 기준의 기존 24회와 수정한 정상 중첩 3회는 기대 판정과 일치했습니다.
한 번의 27회 실행이 전부 통과했다고 해석하지 않습니다. 두 실행의 프롬프트 SHA는 같습니다.
최종 9개 후보 SHA-256은 `c56496293f44d42cb7b9fdeb3d429d815b8f513550107f3d129bb2bfcbfb75b4`입니다.
최종 검사 프롬프트 SHA-256은 `ecabb8fa72cdc22f6e2338d72a3c1ad86f9d983954f5c07a42615bff489e5f4b`입니다.
정상 중첩 후보의 검사 시간은 79.944초, 110.172초, 109.536초입니다. 현재 API 시간 제한의 적합성 증거가 아닙니다.

### 한 후보 재검사

저장소 루트에서 아래 명령을 시작합니다. 검사는 빈 임시 디렉터리에서 실행합니다.
Claude Code의 기존 구독 로그인이 필요합니다.
구독 사용량을 소모합니다. 결과의 실제 모델과 `structured_output`을 확인합니다.

```sh
quantity_repo="$PWD"
quantity_run_dir="$(mktemp -d)"
cd "$quantity_run_dir"
python3 -c 'import json,sys; c=json.load(open(sys.argv[1]))["cases"][0]; print(json.dumps({"original_request":c["original_request"],"candidate":c["candidate"]},ensure_ascii=False))' "$quantity_repo/docs/research/fixtures/quantity-reduction-checks.json" |
claude -p --model claude-haiku-5-5 --effort xhigh --tools '' \
  --disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --setting-sources '' --settings '{"forcedLoginMethod":"claudeai","disableAllHooks":true}' \
  --no-session-persistence --output-format json \
  --system-prompt "$(cat "$quantity_repo/services/api/src/development_ai/check.md")" \
  --json-schema "$(cat "$quantity_repo/services/api/src/development_ai/check.json")"
```

## 보관과 기술 검증

합성 원문과 응답, 프롬프트·schema 스냅샷, 각 실행의 SHA-256을 로컬에 보존했습니다.
경로는 `quantity-evaluation/`, `quantity-evaluation-v2/`, `quantity-evaluation-v3/`, `quantity-evaluation-nested-disjoint/`입니다.
로컬 원문 보관 기한은 2026-11-08입니다. 자동 삭제는 설정하지 않았습니다.
운영 로그에 사용자 목표·자료·응답 원문을 추가하지 않았습니다.

repository/workflow 검사, Python 107개, Rust 전체 단위 검사 24개, `git diff --check`가 통과했습니다.
Rust 외부 DB 통합 검사 10개는 실행하지 않았습니다.
iOS Debug 빌드와 플래그 OFF 화면을 확인했습니다.
프롬프트 보정의 실제 API 인증·출력 상한·비용·지연 적합성은 [#47](https://github.com/minjunkim-dev/smallnext/issues/47)에서 별도로 확인해야 합니다.
구독 CLI에서 검사 수용이 나왔다고 실제 API나 출시 품질을 승인하지 않습니다.

2차 24검사의 CLI 시간 중앙값은 23.0745초, 최대는 79.945초입니다.
thinking 포함 출력 합계는 184,906토큰, 단일 최대는 19,220토큰입니다.
현재 서버 API의 출력 상한 8,192와 HTTP 호출 제한 30초를 CLI에서 강제하지 않았습니다.
구독 CLI의 시간과 토큰은 API 청구액이나 API 실행 시간을 뜻하지 않습니다.
현재 API 제한에서 완료할지는 미검증입니다. 제한을 늘리거나 출시 차단을 해제하지 않았습니다.

## iOS 시뮬레이터 재검증

iPhone 18 Pro / iOS 27.0의 별도 QA 시뮬레이터에서 합성 업무 목표를 사용했습니다.
기존 완료한 첫 행동을 보존한 상태로 재검증했습니다. 과거 첫 행동 자체는 이미 완료 상태입니다.
기존 Claude Code 구독 로그인과 Haiku 5.5/xhigh로 생성·검사를 수행했습니다.

| 직접 조작 | 결과 |
| --- | --- |
| 이전에 거절된 다음 행동의 수동 재시도 | 수용. 둘째 목차 항목을 작성하는 행동을 표시했습니다. 첫 행동 완료 기록은 유지했습니다. |
| 새 둘째 목차 행동에서 더 작게 | 수용. 열린 목차 항목 선택을 구체적인 제목으로 좁혔습니다. 2분에서 1분 카드로 전환했고 분할 원본을 보존했습니다. |
| 되돌리기 | 2분의 원래 행동과 완료 조건을 복원했습니다. 작은 행동은 확정 정책대로 보류로 보존했습니다. |
| 보류 맥락이 추가된 상태에서 더 작게 2회 | 두 후보를 거절했습니다. 기존 행동·완료 기록을 유지했습니다. 마지막 후보와 검사 이유 원문을 기록했습니다. |
| 앱 종료 후 같은 ON 인수로 재실행 | 2분 행동과 거절 안내를 복원했습니다. 첫 행동 완료 결과와 보류된 작은 행동을 DB에서 확인했습니다. |

마지막 후보는 status=need_info였지만 action에는 실제 질문 대신 `행동 제안 없음 (첫 막힘 확인 필요)`를 넣었습니다.
실제 질문은 reason에 들어 있었습니다. 보류 작업과 미완료 기록을 반복 시작 실패의 근거로 해석했습니다.
입력에는 반복 시작 실패를 명시한 사실이 없었습니다. 이 부적합 후보를 적용하지 않았습니다.
첫 추가 거절 후보 원문은 보관하지 않았으므로 그 정확한 이유는 확정하지 않습니다.
이 추가 입력은 보류 행동이 생겼으므로 과거 첫 행동의 `더 작게` 입력과 같지 않습니다.

자동 리뷰 보정 후 같은 앱 상태에서 `더 작게`를 한 번 더 요청했습니다.
생성기는 반복 시작 실패를 추정하지 않았습니다. 그러나 smaller에 허용하지 않는 status=no_action을 생성했습니다.
Rust 구조 검사가 별도 의미 검사 전에 차단했습니다. 기존 행동과 완료 기록은 유지했습니다.
이 요청을 정상 축소 성공으로 기록하지 않습니다. 생성 품질과 실제 API 적합성은 #47에서 남아 있습니다.

생성기에서 여전히 부적합 후보가 나올 수 있습니다. 검사 기준 보정을 전체 AI 품질 통과로 기록하지 않습니다.
실패 후보를 자동 수정·재생성하거나 거절을 우회하지 않았습니다. 추가 요청은 검증자가 수동으로 수행했습니다.
완료한 실제 외부 보고서나 실제 사용자 시작을 검증한 것은 아닙니다.
실기기·VoiceOver·큰 Dynamic Type·모션 성능과 실제 API를 검사하지 않았습니다.
임시 QA 서버는 검증 후 중지했습니다. 등록된 플래그 기본값은 OFF입니다.

후속 요청별 status 계약과 미사용 후보·생성기·연결 평가는 [별도 기록](generator-checker-validation.md)에 있습니다.
이 문서의 이전 보정 결과와 실패는 후속 결과로 대체하지 않습니다.

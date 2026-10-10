# Issue #96: 실제 Rust HTTP/iOS 검사 지연

Claude Code 구독 OAuth·`claude-haiku-5-5`·요청 effort `xhigh`를 유지했다.
개발 API의 Codex 명령을 수동 QA 어댑터로 연결했다.
운영 공급자, Rust 검증 함수, iOS 상태 전환, 피처 플래그 기본값은 바꾸지 않았다.
출력 경로와 형식 지시를 함께 비교했다. 형식 도구만의 효과로 분리하지 않는다.
모델 내부 effort를 독립 증명하지 않는다.

## 재현과 계측

`checker-latency-checks.json`의 원래 보고서 입력을 사용했다.
HTTP 재생과 iOS의 실제 `더 작게` 요청은 같은 생성 입력 해시를 반환했다.
해시: `50ac8ea677b9f8c64fa526dd480b9666ac8801365d54912106bb0e642c91e728`.
기존 QA 시뮬레이터의 로컬 DB를 백업했다. 완료·보류·미완료 행동을 유지했다.

기존 구조화 출력의 HTTP 재생은 66.142초에 수용했다.
생성 API는 25.840초, 검사 API는 37.748초였다.
동일한 iOS 입력에서는 생성 스키마 보정이 두 번째 메시지를 시작했다.
어댑터는 추가 요청을 차단했다. 34.599초 뒤 화면에 실패가 표시됐다.
이 실패는 검사 호출 전에 발생했다. 모델 일반 능력의 결함으로 단정하지 않는다.

단일 JSON 경로의 실제 iOS 요청은 생성·독립 검사를 거쳐 확인 질문을 표시했다.

| 구간 | 초 |
| --- | ---: |
| 생성 CLI 전체 / API | 24.458 / 23.301 |
| 검사 CLI 전체 / API | 22.376 / 21.403 |
| Rust 응답 작업 전체 | 47.201 |
| Rust 나머지 처리: 전체 − 두 CLI | 0.367 |
| iOS HTTP 전체 | 47.206 |
| HTTP − Rust 작업: 루프백 전송 등 | 0.005 |
| 요청 시작 → iOS HTTP 시작 | 0.010 |
| HTTP 완료 → 상태 관찰 | 0.047 |
| 요청 시작 → 상태 관찰 | 47.264 |

`Date`와 `SystemTime`의 같은 호스트 시계를 사용했다.
상태 관찰은 `CoreFlowView.onChange` 시점이다. 물리 화면의 첫 픽셀 표시 시간이 아니다.
UI snapshot으로 대기 표시가 사라지고 확인 질문이 표시된 것도 확인했다.
계측은 날짜와 단계만 기록했다. 입력·응답 본문과 인증정보는 로그에 넣지 않았다.
임시 `[DEBUG-http96]` 계측을 모두 제거하고 앱을 다시 빌드했다.

별도 단일 JSON HTTP 재생은 40.589초에 수용했다.
새 생성 후보는 기존 후보와 다르다. 66.142초와의 차이를 통제된 인과 비교로 주장하지 않는다.
진단용 30초 assertion은 두 경로 모두 실패했다. 제품 SLA는 확정하지 않았다.
남은 40–47초 대기는 대부분 모델 생성·검사 처리다.

## 최소 변경

`scripts/oauth_bridge.py`는 PR #100의 `oauth_quality.call`을 재사용한다.
기본 출력은 `text-json`이다. 기존 `structured`는 명시적 비교에만 사용한다.
입력·프롬프트·출력 스키마를 Rust CLI 호출에서 그대로 읽는다.
단일 메시지, 실제 완료 모델, 중복 키·타입·필수 필드·추가 필드 검사를 유지한다.
검증된 답만 기존 Rust 이벤트 형식으로 전달한다.
Rust는 남은 범위·완료 ID·미완료 상태·가용 시간·다섯 의미 기준을 다시 확인한다.
어댑터를 SIGKILL로 종료해도 작업 프로세스가 소유권 상실을 확인한다.
작업 프로세스는 Claude 프로세스 그룹을 종료하고 회수한다.
재시도·자동 수용·검사 생략·effort 변경은 없다.

어댑터 기록은 시간·입력/프롬프트/스키마/실행기 해시와 안전한 이벤트 요약만 보관한다.
모델 출력, 추론 원문, 인증정보는 보관하지 않는다.

## 직접 실행

Python 3·고정 Rust·로그인한 Claude Code를 사용한다.
아래 명령은 루프백 전용 개발 라우터를 실행한다. DB와 운영 인증 경로는 실행하지 않는다.
`PATH` 변경은 이 개발 서버 프로세스에만 적용한다.

```sh
mkdir -p work/http-oauth-bin work/http-oauth-records
# 아래 두 절대 경로와 Python·Claude 경로를 바꾼다.
cat > work/http-oauth-bin/codex <<'SH'
#!/bin/sh
exec /절대/경로/python3 /저장소/scripts/oauth_bridge.py \
  --claude /절대/경로/claude --records /저장소/work/http-oauth-records "$@"
SH
chmod +x work/http-oauth-bin/codex

PATH="$PWD/work/http-oauth-bin:$PATH" cargo run --locked \
  --manifest-path services/api/Cargo.toml --example oauth-http-diagnosis
```

iOS Debug 실행 인자:
`-ios_core_flow YES -development_ai_url http://127.0.0.1:18996`.
개발 QA 어댑터를 넣지 않은 API는 기존 Codex 공급자를 유지한다.
실기기·VoiceOver·운영 활성화·배포·제품 응답 SLA는 이 결과의 범위 밖이다.

## 회귀와 품질

어댑터 경계의 오프라인 회귀를 먼저 실패시켰다.
기본 출력 경로와 종료 소유권을 수정한 뒤 회귀 4개가 통과했다.
기존 하네스 회귀 25개도 유지한다.
Python 전체 136개·Rust 30개·iOS 87개가 통과했다.
API fmt/clippy/OpenAPI와 저장소·정책·diff 검사도 통과했다.
Rust DB 전용 11개는 로컬 실행에서 제외했다. 변경은 개발 QA 어댑터와 루프백 example이다.
iOS 회귀의 기존 actor 경고 3건은 수정하지 않았다.

새 동결 품질 실행은 **43/47**이다. 고정 검사 32/33, 실제 Rust HTTP 생성·검사 11/14다.
모델 역할 59회, 메시지 59개, 추가 요청 0개, max_tokens 0개다.
완료 모델은 59회 모두 `claude-haiku-5-5`다. 유효 출력은 55회다.
남은 프로세스 그룹과 미회수 프로세스는 0개다.
`useful-minimum-unknown-invalid` 검사, `generate-missing-evidence` 검사,
`useful-minimum-unknown` 생성, `useful-minimum-known` 생성에서 출력 형식 검증이 실패했다.
네 출력은 모두 차단했다. 잘못 수용한 후보가 확인된 것은 아니다.
43/47을 47/47 성공이라고 바꾸지 않는다.

최초 오류 값은 안전한 수신 기록에 저장하지 않았다.
JSON 구문·중복 키·개별 필드 타입 중 어느 오류인지는 소급 확정하지 못한다.
별도 진단은 값과 추론 원문 대신 구문 오류 여부·중복 키 여부·고정 스키마 필드 이름만 계측했다.
고정 실패 검사 2회와 직접 생성 4회의 진단에서는 오류가 재현되지 않았다.
직접 생성 진단은 Rust의 JSON 직렬화 바이트와 다를 수 있다. 이 결과로 실제 경로의 오류 해결을 주장하지 않는다.
이어서 실제 Rust HTTP의 실패 생성 사례 3건을 같은 입력·생성 역할·스키마로 다시 진단했다.
세 생성 입력의 해시와 생성 프롬프트·스키마 해시는 최초 실행과 일치했다.
세 건 모두 생성·독립 검사에서 수용했다. 추가 요청과 형식 오류는 없었다.
검사 후보는 새로 생성했다. 최초 `generate-missing-evidence` 검사 후보의 정확한 재생은 아니다.
추가 진단은 최초 43/47 실행을 덮어쓰거나 앱에서 자동 재시도한 결과가 아니다.

이전 13/14·45/47 수신 기록은 바이트 단위로 보존했다.
[새 수신 기록](fixtures/http-ios-checker-results.json)은 실제 경로의 품질과 한계를 분리한다.
전체 원본은 로컬 `work/http96-quality/`·`work/http96-text/`·`work/http96-audit/`에 보관한다.
검사 기준과 차단을 보존했지만 출력 형식 오류의 제거는 입증하지 못했다.
#96은 열린 상태로 유지한다. 남은 출력 형식 실패를 다음 재현 대상으로 삼는다.

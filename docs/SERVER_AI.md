# 사용자용 서버 AI 실행과 검증

인증·권한·철회·보관의 확정 답은 [#75](https://github.com/minjunkim-dev/smallnext/issues/75)에 있습니다.
코드는 기본 OFF입니다. 서버 배포와 실제 Firebase 연결은 아직 검증하지 않았습니다.
실제 API 품질·청구·지연은 [#47](https://github.com/minjunkim-dev/smallnext/issues/47)에서 검증합니다.
사용자용 서버 모델 변경은 [#47의 Haiku 결정](https://github.com/minjunkim-dev/smallnext/issues/47#issuecomment-6074604866)을 따릅니다.
추론 강도 변경은 [#47의 xhigh 승인과 검증 범위](https://github.com/minjunkim-dev/smallnext/issues/47#issuecomment-6075071867)를 따릅니다.
제한 구독 평가의 결과와 남은 오수용은 [Haiku 평가 기록](research/haiku-server-ai-evaluation.md)에 있습니다.
요청별 계약 회귀와 미사용 후보·생성 단독·연결 결과는 [생성·검사 분리 평가](research/generator-checker-validation.md)에 있습니다.
[#61의 실기기 검증](https://github.com/minjunkim-dev/smallnext/issues/61#issuecomment-6049652307)은 보류 상태입니다.

## 서버 계약

공개 계약은 Rust에서 생성한 [OpenAPI](../contracts/openapi.json)가 기준입니다.
`POST /v1/suggestions`는 `user_server_ai`가 ON일 때만 등록됩니다. OFF에서는 404입니다.
요청은 `state_key`와 기존 `AiInput`을 포함합니다. 본문 전체의 한도는 32 KiB입니다.
앱은 HTTPS의 `Authorization: Bearer`로 Firebase ID token을 보냅니다.
서버는 RS256 서명, 발급자, 프로젝트, 만료, 발급·인증 시각, 주체와 익명 인증을 확인합니다.
서버는 UID 허용 목록과 Firebase의 계정 비활성화·삭제·철회를 확인합니다.
계정 상태는 각 요청에서 조회합니다. 조회 실패에서는 AI를 호출하지 않습니다.
Firebase 공개 키와 서버 OAuth access token만 유효기간 동안 메모리에 캐시합니다.
서버 OAuth는 Firebase 관리용 서비스 계정입니다. 개인 Codex OAuth와 다릅니다.

서버는 요청자 UID·목표 상태 키·요청 종류의 활성 요청을 PostgreSQL transaction advisory lock으로 제한합니다.
다른 사용자도 공유 개인 검증 예산을 사용합니다. 이 한도는 일반 사용자 서비스 요금이 아닙니다.
프로세스마다 최대 2개의 활성 제안을 허용합니다. DB 연결 5개에서 비용 정산 연결을 확보합니다.
정상 경로는 생성 1회와 의미 검사 1회입니다. 자동 재시도·재생성·모델 대체는 없습니다.
서버는 개발 실행기의 입력·후보·의미 검사 규칙을 재사용합니다. CLI를 실행하지 않습니다.
사용자용 생성과 별도 검사는 Anthropic `claude-haiku-5-5`를 사용합니다.
두 역할은 adaptive thinking과 `xhigh`로 고정합니다. 개발 전용 구독 모델은 유지합니다.
반복 시작 실패를 입력이 명시하고 원인을 모르면 첫 실제 걸림돌을 직접 묻는 공통 지침을 사용합니다.
이 경우 더 작은 신체 동작을 제안하는 후보도 검사에서 거부하게 합니다.
개발 CLI와 사용자용 API는 같은 생성·검사 지침을 사용합니다. 요청별 허용 status를 생성 schema와 구조 검사에서 함께 사용합니다.
알려진 제목 복사를 알 수 없는 과거 사실의 근거 확보로 취급하지 않습니다. 제목 작성 자체가 목표인 경우와 구분합니다. 이 지침이 모든 의미 오류를 막는다고 보장하지 않습니다.
거부·불확실·실패·취소에서는 적용 후보를 반환하지 않습니다.
앱은 기존 리비전 검사를 유지합니다. 늦은 응답으로 진행 상태를 바꾸지 않습니다.
인증 준비 제한은 20초입니다. 생성·검사 전체 제한은 120초입니다. 앱 통신 제한은 160초입니다.
응답 본문은 `disposition`, `proposal`, 역할별 `usage`, 서버 처리 시간 `elapsed_ms`를 포함합니다.
수용 외 `proposal`은 null입니다.
`usage`의 비용은 할인과 실제 청구를 확인한 값이 아닙니다. 설정한 보수적 단가로 계산한 상한입니다.
`input_tokens`는 Anthropic의 비캐시 입력·캐시 읽기·캐시 쓰기의 합입니다.
`output_tokens`는 thinking을 포함합니다. `reasoning_tokens`는 제공사가 별도 개수를 주지 않으면 null입니다.

## 비용과 보관

금액 단위는 micro-USD입니다. `1_000_000`은 1 USD입니다.
각 호출은 확인한 모델의 전체 입력 context 상한과 출력 토큰 상한을 기준으로 예약합니다.
문자 수로 정확한 토큰 수를 추정하지 않습니다. 전체 context를 예약하므로 실제 작은 요청도 차단될 수 있습니다.
생성·검사의 두 호출을 함께 승인합니다. 월 합계 행을 잠그고 예약을 먼저 commit합니다.
사용량을 확인한 부분만 정산합니다. 확인하지 못한 부분은 호출 상한으로 유지합니다.
취소·재시작·DB 정산 오류에서 예약을 임의로 환급하지 않습니다.
제공사가 확인한 토큰 상한을 넘기면 남은 예산을 소진 처리합니다. 해당 월의 새 요청을 차단합니다.
제공사 응답의 모델이 확정 모델과 다르면 단가와 상한을 확인할 수 없습니다. 사용량으로 환급하지 않고 해당 월의 새 요청을 차단합니다.
다른 요청의 정산·프로세스 재시작·한도 증가도 해당 월의 차단을 풀지 않습니다.
초기 실행 한도는 첫 평가 3 USD로 더 좁게 제한합니다. 월 개인 검증 최대 10 USD를 늘리지 않습니다.
초기 평가 이후 추가 실행 범위는 #47에서 정합니다. 한도 변경으로 예약 비용을 초기화하지 않습니다.

요청 메타데이터와 UID·목표·자료·AI 응답·인증 토큰 원문을 DB나 운영 로그에 저장하지 않습니다.
역할별 사용량은 요청 응답에서만 확인합니다. 이 구현의 요청 메타데이터 보관 기간은 0일입니다.
DB에는 현재 UTC 월의 합계와 초과 차단 상태 하나만 저장합니다.
이전 월의 합계는 서버 시작과 실행 중 매분 삭제합니다. OFF에서도 삭제를 수행합니다.
배포자는 API가 중지된 때에도 월 경계의 삭제 작업을 실행해야 합니다.
배포 전 월 경계의 스케줄러와 DB 백업 보관 범위를 확인합니다. 현재 저장소는 스케줄러 배포를 완료하지 않았습니다.

```sh
# 운영 스케줄러가 현재 월 이전의 합계만 삭제할 때 실행할 명령입니다.
# DATABASE_URL은 비밀정보 제공 경로로 주입합니다.
cargo run --locked --manifest-path services/api/Cargo.toml --bin purge-ai-budget
```

## 실제 연결 전에 설정할 값

1. `.env.example`의 사용자용 항목을 로컬 비밀정보 제공 경로에 설정합니다. 기존 `.env`를 덮어쓰지 마십시오.
2. `FIREBASE_PROJECT_ID`와 실제 허용 UID 목록을 설정합니다. `AI_ALLOWED_FIREBASE_UIDS`는 쉼표로 구분합니다.
3. 같은 프로젝트의 서비스 계정 파일 경로를 설정합니다. 최소 권한 `firebaseauth.users.get`을 확인합니다. 파일을 앱·이미지·Git에 넣지 마십시오.
4. #47에서 `claude-haiku-5-5 / xhigh`의 계정 API 접근, 현재 단가와 전송·보관 조건을 확인합니다. `ANTHROPIC_API_KEY`는 서버에만 설정합니다.
5. 확인 근거를 남긴 뒤 `AI_MODEL_CONFIRMED=1`과 `USER_SERVER_AI=1`을 설정합니다. 첫 평가 합계는 3 USD 이하로 유지합니다.

`AI_INPUT_MICRO_USD_PER_MILLION`은 캐시 쓰기를 포함한 입력의 최대 단가를 사용합니다.
캐시 읽기 할인으로 예산을 줄이지 않습니다. 출력 단가는 reasoning 토큰을 포함합니다.
2026-10-09 공식 모델 문서에서 전체 context 1,000,000·최대 출력 128,000을 확인했습니다.
서버는 전체 context를 1,000,000으로 고정 검증합니다. 예제 출력 제한은 thinking을 포함해 8,192입니다.
`xhigh`의 실제 API 출력·시간 제한 적합성은 미확인입니다. [제한 평가](research/haiku-server-ai-evaluation.md)의 결과와 별도로 실제 API 제한을 검증하기 전까지 서버를 OFF로 준비합니다.
짧은 입력의 할인 단가로 예약하지 않습니다. 긴 입력의 1시간 cache write 최대 단가 $1/MTok과 출력 $2.50/MTok을 최소 예약 단가로 사용합니다.
예제 설정의 두 호출 예약은 2.040960 USD입니다. 이는 API 청구 예상액이 아닙니다.
구성 단가가 이 최소값보다 낮으면 시작을 거부합니다. 가격이 바뀌면 최소값과 확인 기록을 함께 갱신합니다.
필수 값이 없거나 두 호출 예약이 평가 예산보다 크면 서버 시작을 거부합니다.
`USER_SERVER_AI=0`은 정적 기본값보다 우선합니다. 잘못된 명시 값도 OFF입니다.
`AI_MODEL_CONFIRMED=1`은 확인 기록을 대신하지 않습니다. 모의 응답으로 API 가용성을 확인했다고 보고하지 마십시오.
TLS·서버 주소·허용 사용자·IAM·삭제 스케줄러를 준비하기 전에는 사용자용 서버를 공개하지 마십시오.
제공사 요청은 Anthropic Messages의 단일 user message와 JSON schema 출력입니다.
`tools=[]`, `stream=false`, `service_tier=standard_only`를 지정합니다. cache_control과 사용자 식별 메타데이터를 보내지 않습니다.
OpenAI 전용 `store`·`background` 필드는 보내지 않습니다. 제공사의 보관을 끄는 요청 옵션으로 보고하지 마십시오.
제공사의 실제 보관·학습 사용·전송 조건은 #47에서 확인합니다.
응답은 확정 모델·end_turn·assistant text 1개만 허용합니다. thinking 내용은 사용량 외 응답·DB·로그에 남기지 않습니다.
출력 중단·거부·도구 호출은 적용하지 않습니다. 모델 불일치와 캐시 포함 context 초과는 해당 월을 차단합니다.

## iOS 연결

FirebaseAuth와 FirebaseCore 12.19.2를 사용합니다. Analytics 제품은 앱에 연결하지 않습니다.
Firebase가 익명 계정과 토큰 갱신·Keychain 보관을 관리합니다. 앱의 진행 상태는 GRDB에 유지합니다.
서버 401 뒤에는 같은 AI 요청을 자동 재전송하지 않습니다.
다음 Xcode build settings에 해당 Firebase 앱의 공개 client 설정을 넣습니다.
서버의 제공사 API 키와 서비스 계정 파일은 이 설정에 넣지 않습니다.

| 설정 | 값 |
| --- | --- |
| `SMALLNEXT_API_BASE_URL` | 경로·쿼리·사용자 정보가 없는 HTTPS 서버 원점 |
| `SMALLNEXT_FIREBASE_APP_ID` | 등록한 iOS Firebase app ID |
| `SMALLNEXT_FIREBASE_SENDER_ID` | 같은 app ID의 숫자 sender ID |
| `SMALLNEXT_FIREBASE_PROJECT_ID` | 서버와 같은 Firebase project ID |
| `SMALLNEXT_FIREBASE_API_KEY` | Firebase client API key; 서버 AI 제공사 키가 아님 |

Debug에서만 `-user_server_ai YES`로 로컬 ON을 지정할 수 있습니다.
서버 주소만 `-server_ai_url https://...`로 바꿀 수 있습니다. 평문 HTTP는 거부합니다.
설정이 없거나 잘못되면 `사용 불가`를 반환합니다. 개발 CLI 공급자로 자동 전환하지 않습니다.
OFF에서는 기존 Debug 개발 공급자·고정 공급자와 Release 사용 불가 경로를 유지합니다.
`ios_core_flow`도 별도로 ON이어야 현재 행동 화면을 사용할 수 있습니다.
홈에서 실행 인자 없이 재실행하면 Debug ON 인자가 유지되지 않을 수 있습니다. 검증 시 같은 실행 인자를 유지하십시오.

## 검사

```sh
make api-check api-spec-check
make api-test-db
make ios-check IOS_SIMULATOR='iPhone 18 Pro'
```

일반 API 검사는 실제 서비스 계정과 키를 사용하지 않습니다.
DB 검사는 `TEST_DATABASE_URL`의 격리 schema에서 HTTP 경계를 검증합니다.
합성 RSA 키·Firebase 키 응답·계정 상태·제공사 응답을 사용합니다.
정상·거부·불확실·잘못된 구조·위조 토큰·철회·예산 경합·재시작·취소를 확인합니다.
앱 공급자 검사는 인증·전송 오류에서 재시도하지 않는지와 기존 후보 매핑을 확인합니다.
실제 Firebase 프로젝트·서버 IAM·API 청구·배포·실기기 검사는 별도로 남깁니다.

## 공식 계약

- [Firebase ID token 검증](https://firebase.google.com/docs/auth/admin/verify-id-tokens)
- [Firebase 철회 확인](https://firebase.google.com/docs/auth/admin/manage-sessions)
- [Firebase 계정 조회](https://docs.cloud.google.com/identity-platform/docs/reference/rest/v1/projects.accounts/lookup)
- [Anthropic Messages 요청·응답·사용량](https://platform.claude.com/docs/en/api/messages/create)
- [Haiku 5.5 모델·가격·한도](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
- [추론 강도](https://platform.claude.com/docs/en/build-with-claude/effort)
- [JSON schema 출력과 지원 범위](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

검사 schema의 숫자 범위는 Messages API가 지원하는 정수 enum으로 전송합니다.
원래 검사 기준 1~5의 의미와 서버의 `validate_check`는 유지합니다.

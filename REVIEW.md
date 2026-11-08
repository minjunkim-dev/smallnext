# 리뷰 기준

리뷰 에이전트가 읽는 파일이다. 구현 에이전트에게 상시 주입하지 않는다. 구현자는 관련 Issue·도메인 문서와 [WORKFLOW](docs/WORKFLOW.md)를 읽는다.
리뷰는 구현과 다른 컨텍스트에서 한다. 입력은 변경분(diff), 이 파일, Issue의 확정 완료 조건이다. 입력 준비와 변경 영역별 상세 문서는 [로컬 독립 리뷰](docs/agents/review.md)에 있다.

## 실패로 보는 것

| 영역 | 실패 |
| --- | --- |
| 공통 | 기존 언어·계층·공통 interface를 버린다. 필요 없는 dependency·formatter를 더한다. 같은 책임의 helper를 두고 새로 만든다. 범위 밖 리팩터나 저장소 전체 포맷 |
| 동작 | Issue의 확정 완료 조건과 다르다. 피처 플래그 OFF 경로가 기존 동작을 바꾼다. 저장 데이터·상태 전환·비동기 처리·오류 복구·접근성이 회귀한다. 호출자가 쓰는 interface의 정상·실패 경로를 실행하지 않았다 |
| 화면 | 사용자에게 필요 없는 정보를 표시한다 |
| 테스트 | 확인한 버그를 수정 전 실패하는 검사로 재현하지 않았다(기존 검사가 재현하면 중복하지 않는다). 상수 재단언, 소스 문자열 순서, 성공만 반환하는 mock을 동작 검증이라고 한다. 문서·설정 변경을 복제하는 테스트. 정적 검사는 action SHA·권한·문서 링크 같은 정적 제약에만 쓴다 |
| API | OpenAPI·앱 호출자·기존 DB transaction·경합·롤백·삭제 범위를 함께 보지 않았다. 사용자용 서버 AI 기본 OFF나 인증 조회 실패 시 호출 금지를 깬다. 예산 예약·정산·취소·시간 제한, 자동 재시도·재생성·모델 대체 금지, 미확인 사용량의 임의 환급 금지가 [SERVER_AI](docs/SERVER_AI.md) 계약과 다르다 |
| iOS·Android | 목표·완료·보류·중단·삭제의 도메인 의미가 플랫폼마다 다르다. 저장·복구·취소·늦은 응답의 리비전을 놓친다. 접근성·앱 수명 주기·네트워크 오류·동의 경계가 깨진다. 앱에 서버 비밀정보를 넣는다. 기기 검증 보류를 단위 테스트·시뮬레이터·archive로 해제한다 |
| 검증 스크립트 | 오류·timeout·취소·하위 프로세스 회수·소유한 임시 파일 정리를 잃는다. 삭제·덮어쓰기·경로 탈출·큰 출력·부분 결과에서 실패를 숨긴다 |
| GitHub 수집·집계·Draft | pagination·최신 attempt·head/base/merge SHA·publisher·최종 상태를 대조하지 않는다. Draft가 main source·같은 SHA의 CI를 확인하지 않거나 기존 Release·태그·asset을 덮어쓴다 |
| 문서 | 사실과 다르다. 명령이 실제로 동작하지 않는다. 하나의 사실을 두 기준 문서에 적는다 |

도메인은 [CONTEXT](CONTEXT.md), 보안·서버 제약은 [SERVER_AI](docs/SERVER_AI.md), 작업·플래그는 [WORKFLOW](docs/WORKFLOW.md), 저작권은 [COPYRIGHT](COPYRIGHT.md)를 따른다.

## 심각도

- P0: 데이터 손실, 보안 구멍, 되돌릴 수 없는 결과. 병합하지 않는다.
- P1: 기능이 틀리거나 깨진다. 병합 전에 고친다.
- P2: 개선 제안. 상한 5개. 넘으면 버린다. 고치지 않으면 후속 Issue나 이유를 남긴다.

## 건너뛸 것

- 포매터·린터(`cargo fmt`·clippy·Android lint·actionlint)가 이미 잡는 스타일.
- 이 PR이 만들지 않은 기존 문제(필요하면 "기존 문제"로 따로 표시한다).
- 생성 파일(`contracts/openapi.json`은 `make api-spec-check`가 대조), lockfile의 해시 줄, `docs/research/fixtures/`.

## 신뢰 경계

Door가 되돌리기 어려움이거나 이 경로를 건드리면 보안 관점의 리뷰를 더한다.

- 공통: `.github/workflows/**`, 저장소·CI 설정(`.github/repository-settings.json`, `.github/dependabot.yml`, `CODEOWNERS`, `.ci/toolchains.json`), 의존성 manifest·lockfile(`Cargo.toml`·`Cargo.lock`, Gradle 파일, `mise.lock`, `skills-lock.json`), 에이전트 권한(`.claude/settings.json`).
- 프로젝트: 인증·익명 계정·AI 예산·동의(`services/api/src/user_ai/**`, `apps/ios/Sources/TurnstileAuthentication.swift`, `apps/ios/Sources/UserServerAI.swift`, `apps/ios/Sources/AIConsent.swift`), DB migration(`services/api/migrations/**`, Android `apps/android/app/src/main/java/dev/smallnext/app/data/AppDatabase.kt`의 `ProgressMigration`), 운영(`infra/production/**`, `scripts/deploy_production.py`, `scripts/prepare_production.py`, `scripts/backup_ai_budget.py`), 독립 집계(`scripts/trusted_ci.py`, `.github/workflows/trusted-aggregation.yml`).

이 경로에서 따로 보는 것:

- 입력은 env와 안전한 argv로 전달한다. 외부 입력을 shell 코드로 삽입하지 않는다.
- 인증·권한·입력 검증은 플래그와 관계없이 수행한다.
- 비밀정보·AI 원문·개인정보를 로그·검토 자료·artifact에 넣지 않는다.
- Actions 기본 권한은 읽기다. 쓰기 권한·Secret은 필요한 job·단계로 제한한다. 제품·dependency 빌드는 배포 쓰기 권한과 production Secret을 받지 않는다.
- 외부 Action은 전체 SHA로 고정한다. 잠금 파일과 [도구 버전](.ci/toolchains.json)을 유지한다.
- 비밀정보가 있는 작업에서는 PR 코드를 실행하지 않는다. `pull_request_target`은 기준 브랜치만 checkout한다. 봇의 자동 승인을 허용하지 않는다.

## 보고와 수정

- 근거는 `file:line`이다. 이름만 보고 추측하지 않는다. 보고는 한국어다.
- 확실한 결함은 직접 고쳐 커밋하고 영향받는 검사를 다시 돌린다. 판단이 필요한 것만 남긴다.
- 지적은 개별 줄이 아니라 버그 유형으로 묶어, 같은 유형을 한 번에 고치게 한다.
- 보고는 지적 개수(P0/P1/P2)로 시작한다. 실제로 실행하지 않은 리뷰를 완료로 적지 않는다. 소스 리뷰만으로 실행·기기·배포를 검증했다고 하지 않는다.

## 라운드

- 최대 3라운드. 2라운드부터는 직전 수정으로 바뀐 부분만 본다.
- 이미 보고한 지적은 다시 보고하지 않는다.
- 3라운드 뒤에도 남으면 목록을 늘리지 말고 구현 방식을 다시 생각하라고 보고한다.

## 배운 규칙

리뷰가 놓친 버그나 반복된 오탐이 생기면 한 줄씩 더한다. 사용자가 승인한 것만 넣는다.

# 초기 셋업 검증 기록

검증일: 2026-10-03 KST.
검증 대상: `chore/initial-monorepo-setup` 작업 브랜치.

## 로컬에서 통과한 검사

| 대상 | 확인 결과 |
| --- | --- |
| iOS | Xcode 27.0, iPhone 18 Pro, iOS 27.0에서 빌드·실행 성공 |
| iOS 저장 | GRDB 재열기·초기 마이그레이션·저장 유지 테스트 1개 통과 |
| Android | Java 21, SDK 36, Gradle 8.13으로 Debug 빌드와 lint 통과 |
| Android 저장 | Pixel 10 API 37 에뮬레이터에서 Room 저장 유지 테스트 1개 통과 |
| API | Rust 1.96.0의 fmt, clippy 경고 검사, DB 없는 테스트 2개 통과 |
| PostgreSQL | PostgreSQL 18 개발 DB 정상 상태; 마이그레이션 재적용과 readiness 테스트 1개 통과 |
| HTTP | 호스트 API와 API 컨테이너의 health·ready 응답이 HTTP 200 |
| API 계약 | Rust 생성 OpenAPI와 커밋 대상 명세의 내용 일치 |
| 컨테이너 | Linux API 이미지 빌드·실행 성공; 일반 사용자 UID 10001 사용 |
| 운영 템플릿 | Compose 구성 검사와 Caddy 설정 검사 통과 |
| CI 선택 규칙 | 공통 계약, 플랫폼별 변경, 문서, 초기 브랜치, 이력 누락, 루트 컨테이너 설정의 테스트 6개 통과 |
| 저장소 | UTF-8, 공백, 로컬 링크, Action 고정 커밋 검사 통과 |

두 앱의 실행 화면에서 `Smallnext`와 `작은 다음 행동을 준비하고 있어요.`를 확인했습니다.
초기 저장 오류 안내는 표시되지 않았습니다.
호스트 API 검증에는 18080, 컨테이너 검증에는 18081 포트를 사용했습니다.
개발 실행의 기본 API 포트는 8080입니다.
테스트용 DB 파일은 앱의 실제 DB 파일과 분리했습니다.

## 아직 확인하지 않은 항목

- iPhone·Android 실기기의 실행, 서명, 스토어 설치.
- 목표·행동 기능, 실제 Firebase 인증, AI, 기기 간 동기화.
- 실제 도메인의 인증서 발급, 관리형 DB 연결, 운영 배포, DB 백업 복구.

## GitHub 등록과 원격 CI

사용자의 등록 승인 후 [Issue #13](https://github.com/minjunkim-dev/smallnext/issues/13)과
[PR #14](https://github.com/minjunkim-dev/smallnext/pull/14)를 등록했습니다.
초기 원격 실행에서 iOS 빌드·테스트, Android 빌드·lint,
API 검사와 PostgreSQL 테스트가 통과했습니다.
Android 에뮬레이터 단계의 SDK 도구와 `adb` 경로 오류를 수정했습니다.

위 표는 로컬 검증 결과입니다.
최종 커밋의 원격 CI 결과는 [PR 검사 목록](https://github.com/minjunkim-dev/smallnext/pull/14/checks)에서 확인합니다.
실기기·제품 기능·운영 배포의 검증 결과는 포함하지 않습니다.

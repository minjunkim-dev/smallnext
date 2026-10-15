---
status: accepted
---

# 초기 사용자 서버의 DB와 익명 인증을 Supabase로 묶는다

## 배경과 결정

2026-10-16 기록. 사용자는 무료 시험의 DB와 인증을 Supabase로 통합하도록 확정했다.
확정 범위와 구현 근거는 [Issue #168](https://github.com/minjunkim-dev/smallnext/issues/168)에 있다.
이 ADR은 선택 이유를 보존한다. 운영 준비 완료나 유료 전환을 승인하는 문서는 아니다.

기존 서버는 Rust·PostgreSQL·Compose·Caddy를 사용한다.
서버에는 AI 예산 합계와 차단 상태를 보존할 DB가 필요하다.
앱에는 이메일 가입 없이 사용자용 서버에 접근할 익명 인증이 필요하다.
목표와 진행 상태는 기기에 남는다. 기기 간 동기화는 이번 결정에 포함하지 않는다.

초기 시험은 Supabase Free의 관리형 PostgreSQL과 Auth를 같은 프로젝트에서 사용한다.
Rust 서버는 PostgreSQL 프로토콜로 DB에 연결한다. iOS는 Swift SDK의 Auth product를 사용한다.
Data API·Storage·Realtime·Edge Functions는 도입하지 않는다.
FirebaseCore·FirebaseCrashlytics는 Crashlytics 용도로 유지한다.

## 이 요구에 맞는 이유

1. **기존 DB와 서버 구조를 유지한다.** Supabase는 PostgreSQL DB를 제공한다. 기존 SQL migration·예산 transaction·월 삭제 처리를 유지한다. 새 데이터 모델이나 서버 실행 환경으로 전환할 필요가 없다. [공식 DB 설명](https://supabase.com/docs/guides/database/overview)
2. **DB와 인증의 관리 지점을 줄인다.** DB·Auth를 같은 프로젝트에서 확인한다. 기존 Firebase Auth의 서버용 서비스 계정 JSON·별도 IAM 권한·Google OAuth 경로를 제거한다. Firebase 전체를 제거하는 결정은 아니다.
3. **현재 익명 인증 요구를 지원한다.** Supabase는 익명 로그인과 Swift SDK를 제공한다. 앱은 계정·세션·토큰 갱신을 SDK로 처리한다. 사용자가 허용한 익명 계정 재생성 범위는 #168을 따른다. 서버의 허용 UID·현재 계정·세션 검사는 별도로 유지한다. [공식 익명 인증 설명](https://supabase.com/docs/guides/auth/auth-anonymous)
4. **무료 시험으로 시작할 수 있다.** Free의 제공 범위 안에서 DB와 인증 연결을 시험한다. 운영 비용이 항상 0이거나 운영 부하를 감당한다는 판단은 아니다. 사용량·가용성·복구 요구가 커지면 다시 평가한다.

## 비교한 대안

| 구성 | 이점 | 이번에 선택하지 않은 이유 |
| --- | --- | --- |
| Neon 등 관리형 PostgreSQL + 기존 Firebase Auth | 기존 인증 코드를 유지할 수 있다. | DB와 인증을 나누어 관리하며 Firebase Auth의 서버 자격 증명·권한 관리도 남는다. 사용자가 선택한 DB·Auth 통합 목표와 맞지 않는다. |
| Supabase PostgreSQL + 기존 Firebase Auth | DB 연결부터 바꾸므로 인증 변경 범위를 줄인다. | 인증 운영을 통합하는 효과가 없다. |
| Supabase PostgreSQL + Supabase Auth | 기존 PostgreSQL을 유지하며 DB·Auth 관리 지점을 묶는다. | 채택한다. 대신 Firebase Auth 교체와 인증 의존성 변경 비용을 부담한다. |

이 비교는 현재 Smallnext 구성과 요구를 기준으로 한다.
Neon 등 다른 제품의 Auth 기능 부재를 뜻하지 않는다.
제공사별 성능·가용성·총비용 비교 실험은 하지 않았다. Supabase의 우월성을 입증한 결정은 아니다.

## 비용과 제약

- Firebase Auth SDK와 서버 검증 경로를 바꾸고 회귀 검사를 수행해야 한다. 익명 계정의 연속성을 자동 이전하는 구현은 포함하지 않는다.
- DB는 PostgreSQL을 유지하지만 Auth API·JWT·SDK와 `auth.users`·`auth.sessions`를 확인하는 함수에는 Supabase 의존성이 생긴다. 다른 공급자로 이동할 때 인증 경로와 세션 확인 함수를 바꾸고 재검증해야 한다.
- 같은 프로젝트에 DB와 Auth를 두므로 프로젝트 장애가 두 경로에 함께 영향을 줄 수 있다. Free는 비활성 프로젝트가 일시 중지될 수 있다. [운영 체크리스트](https://supabase.com/docs/guides/deployment/going-into-prod)
- Free의 복구 계획은 제공사의 자동 백업에 의존하지 않는다. 공식 문서는 정기 export와 외부 백업을 권장한다. 백업 주기·보관 기간·RPO/RTO는 아직 미확정이다. [공식 백업 설명](https://supabase.com/docs/guides/platform/backups)
- 인증 통합은 보안 설정 완료를 뜻하지 않는다. 최소 DB 권한·SSL 강제·접속 IP 제한·관리자 MFA·익명 가입 남용 방지와 복구 검증은 실제 운영 전에 확인해야 한다. 익명 가입 CAPTCHA는 앱 연동도 필요하다. [운영 체크리스트](https://supabase.com/docs/guides/deployment/going-into-prod), [익명 가입 남용 방지](https://supabase.com/docs/guides/auth/auth-anonymous#abuse-prevention-and-rate-limits)

실행 절차와 현재 검증 범위는 [서버 AI](../SERVER_AI.md)와 [운영 runbook](../PRODUCTION.md)을 따른다.
#162 전체 실행과 #164 실제 배포의 보류는 유지한다.

## 다시 검토할 조건

Free의 사용량·일시 중지·복구 제약이 실제 요구와 맞지 않으면 요금제와 공급자를 다시 비교한다.
계정 복구·기기 간 동기화·파일 저장 요구가 생기면 해당 요구를 별도로 결정한다.
통합으로 줄인 관리 작업보다 SDK·인증 schema 의존성의 유지 비용이 커지면 구성을 재검토한다.
이 조건은 자동 유료 전환이나 새 기능 도입의 승인이 아니다.

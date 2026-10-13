# PR 품질·Draft CD 검증

작업: [Issue #125](https://github.com/minjunkim-dev/smallnext/issues/125).
확인일: 2026-10-14 KST. base: `22a52959080b4221147fbbbf967c30507b7ff568`.

## 시작 상태

작업 트리는 깨끗했다. 최신 origin/main과 HEAD가 base SHA와 같았다.
열린 기존 PR #104–#109는 dependency 작업이다. 수정하지 않았다.
기존 Release와 Draft 목록은 비어 있었다.
main 보호의 strict 필수 검사는 PR conventions·Repository hygiene·Project checks다.
Actions App ID는 15368이다. enforce_admins·linear history·대화 해결을 요구한다.
GitHub의 필수 승인 수는 0이다. force push와 삭제를 허용하지 않는다.
로컬 독립 리뷰와 위험에 따른 사람 승인은 절차 규칙이다. GitHub가 이 구분을 자동 강제하지 않는다.

## 구현 상태

코딩 규칙·Standards/Spec/보안 리뷰 절차·PR template·Bugbot base 설정·미공개 API Draft workflow를 작업 브랜치에 구현했다.
Claude 댓글 workflow를 제거했다. 과거 리뷰 helper와 보안 회귀 검사는 보존했다.
기존 CI·dependency 검사·독립 집계를 유지했다. App 설치와 전역 계정 연결은 제거하지 않았다.
default branch 반영과 Draft 실제 실행은 최종 head 승인 뒤 확인한다.

## 실제 검사와 독립 리뷰

검사·최종 head·리뷰 결과·PR·CI URL은 검증을 완료한 뒤 기록한다.
첫 로컬 검사에서 Python 3.9의 `hashlib.file_digest` 미지원 오류를 확인했다.
기존 Python에서 실행하는 streaming SHA-256으로 수정했다.

## 외부 설정과 실행

Cursor Bugbot 공식 schema에서 YAML 지원을 확인했다.
개인 override → base branch YAML → 설치 설정 순서로 적용한다.
Manual Only·On-demand는 YAML이 강제하지 않는다. Incremental 기존 값을 유지한다.
계정 기본 화면에서 Manual Only·Default·Draft Off·Autofix Off·위험 점수 On·Incremental Off를 관측했다.
저장소별 설정·요약 출력·On-demand는 별도 확인한다.
계정 기본 설정을 바꾸지 않았다. 새 Bugbot 수동 호출은 아직 하지 않았다.
GitHub App 설치 목록 API는 현재 gh 인증으로 403을 반환했다. 접근 불가를 미설치로 판정하지 않았다.
로컬 Docker daemon은 처음에 실행되지 않았다. 로컬 archive smoke는 아직 수행하지 않았다.

## 남은 검증

최종 head 독립 리뷰·필수 CI·Codex 자동 리뷰 비활성화·저장소 Bugbot 옵션·사람의 최종 head 승인·병합 후 main CI·Draft 실제 실행·다운로드 digest/metadata/smoke를 확인한다.
공개 배포·production 변경·데이터 삭제·스토어 업로드를 수행하지 않았다.

공식 근거: [Cursor Bugbot](https://cursor.com/docs/bugbot),
[GitHub Release API](https://docs.github.com/en/rest/releases/releases),
[GitHub asset API](https://docs.github.com/en/rest/releases/assets).

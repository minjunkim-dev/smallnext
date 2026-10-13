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

이 파일은 구현 단계의 검증 기록이다. 최종 head·리뷰 결과·원격 CI URL은 PR의 Evidence와 별도 최종 검증 보고서에 기록한다.
`python3 scripts/check_repository.py`, `python3 scripts/workflow_policy.py`, `git diff --check` 통과.
`python3 -m unittest discover -s scripts -p 'test_*.py'`: 초기 212개 검사 통과, 53.275초.
`actionlint`: 통과. actionlint 1.7.12, ShellCheck 0.11.0, Python 3.9.6, gh 2.102.0.
첫 로컬 검사에서 Python 3.9의 `hashlib.file_digest` 미지원 오류를 확인했다.
기존 Python에서 실행하는 streaming SHA-256으로 수정했다.
실제 preflight 조회에서 저장소 루트 URL의 trailing slash가 HTTP 404를 만드는 결함을 재현했다.
리뷰어가 metadata 필수 항목 누락, 게시 중 main 상태 재검사와 Release ID에 연결한 asset 업로드도 수정했다.
API는 기존 배포 단위를 유지한다. CI helper의 SHA·pagination·job 목록을 재사용했다. 저장소 전체 리팩터를 수행하지 않았다.

## 외부 설정과 실행

Cursor Bugbot 공식 schema에서 YAML 지원을 확인했다.
개인 override → base branch YAML → 설치 설정 순서로 적용한다.
Manual Only·On-demand는 YAML이 강제하지 않는다. Incremental 기존 값을 유지한다.
계정 기본 화면에서 Manual Only·Default·Draft Off·Autofix Off·위험 점수 On·Incremental Off를 관측했다.
저장소 `minjunkim-dev/smallnext`의 Bugbot enabled를 확인했다. On-demand Spending은 Disabled였다.
현재 개인 PR Summaries는 On이다. As Comment 설정은 새 base YAML의 병합 후 적용 대상이다. 새 요약 댓글 출력은 확인하지 않았다.
계정 기본 설정을 바꾸지 않았다. 새 Bugbot 수동 호출은 아직 하지 않았다.
Claude workflow ID `373871365`를 `gh workflow disable agent-review.yml --repo minjunkim-dev/smallnext`로 비활성화했다.
API로 `state=disabled_manually`를 확인했다. source workflow 제거는 작업 브랜치에만 반영했다.
현재 ChatGPT 계정에는 smallnext가 검색되지 않았다. 사용자가 Codex 외부 설정을 미완료로 남기라고 지정했다.
개인 자동 리뷰 기본값과 다른 계정·프로젝트 연결은 변경하지 않았다.
GitHub App 설치 목록 API는 현재 gh 인증으로 403을 반환했다. 접근 불가를 미설치로 판정하지 않았다.
로컬 Docker daemon은 처음에 실행되지 않았다. 로컬 archive smoke는 아직 수행하지 않았다.

## 남은 검증

최종 head 독립 리뷰·필수 CI·Codex 자동 리뷰 비활성화·저장소 Bugbot 옵션·사람의 최종 head 승인·병합 후 main CI·Draft 실제 실행·다운로드 digest/metadata/smoke를 확인한다.
검증용 후보: `v0.1.0-alpha.20261014`, source `22a52959080b4221147fbbbf967c30507b7ff568`.
이 source의 [Project checks run 38206871524](https://github.com/minjunkim-dev/smallnext/actions/runs/38206871524)은 7개 job 모두 성공했다.
[Repository checks run 38206871247](https://github.com/minjunkim-dev/smallnext/actions/runs/38206871247)도 동일 source에서 성공했다.
최종 PR 승인 뒤 main의 새 정책으로 이 기존 main 제품 source를 빌드한다. API 제품 코드는 이번 PR에서 변경하지 않았다.
공개 배포·production 변경·데이터 삭제·스토어 업로드를 수행하지 않았다.

공식 근거: [Cursor Bugbot](https://cursor.com/docs/bugbot),
[GitHub Release API](https://docs.github.com/en/rest/releases/releases),
[GitHub asset API](https://docs.github.com/en/rest/releases/assets).

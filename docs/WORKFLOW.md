# 협업 규칙

## main 중심 trunk-based 개발

`main`은 유일한 통합 브랜치입니다. 개발용 `dev`, `develop`, 장기 기능 브랜치는 사용하지 않습니다.
항상 실행 가능한 변경을 작은 단위로 병합합니다. 한 브랜치는 한 목적을 가집니다.
당일 병합을 목표로 합니다. 2작업일을 넘기면 변경을 나눕니다.
기능 전체가 완료될 때까지 브랜치를 유지하지 않습니다. 미완성 기능은 피처 플래그로 숨깁니다.

1. Issue에 문제, 범위, 완료 조건, 검증 방법을 기록합니다. 결정은 질문과 확정 답을 기록합니다.
2. 최신 `origin/main`에서 작업 브랜치를 만듭니다. 공유 checkout을 전환하기 전에 다른 작업을 확인합니다.
3. 동작을 보존하는 작은 변경을 작성합니다. 검사를 실행하고 Draft PR을 일찍 만듭니다.
4. 최신 커밋의 CI와 AI 리뷰를 확인합니다. 결함을 수정하고 플래그 OFF·ON 결과를 기록합니다.
5. 사람이 최종 확인한 후 squash로 병합합니다. 병합 후 브랜치를 삭제합니다.

```sh
git fetch origin
git switch -c feat/17-goal-split origin/main
```

도구가 RTK를 제공하면 셸 명령 앞에 `rtk`를 사용합니다.
관련 없는 변경은 제외합니다. 공동 브랜치를 강제 푸시하지 않습니다.

## 브랜치와 커밋 이름

브랜치 형식은 `<type>/<issue>-<description>`입니다. 소문자, 숫자, 하이픈을 사용합니다.
`docs`, `build`, `ci`, `chore`의 작은 유지보수는 Issue 번호를 생략할 수 있습니다.
그 외 유형은 Issue 번호가 필요합니다. 구현 범위가 있는 작업은 유형과 무관하게 Issue를 연결합니다.

허용 유형: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`, `revert`.
자동 생성 브랜치는 `claude/<description>`, `codex/<description>`, `dependabot/<description>`을 허용합니다.
봇 브랜치도 PR 제목, 검증, Issue 연결, 병합 규칙을 따릅니다.

커밋과 PR 제목은 Conventional Commits 형식을 사용합니다.
`<type>(<scope>): <description>`에서 scope는 선택입니다. 호환성을 깨면 `!`와 본문의 `BREAKING CHANGE:`를 사용합니다.
설명은 영어 소문자 동사로 시작합니다. 제목은 72자 이내로 쓰고 끝에 마침표를 쓰지 않습니다. Dependabot PR 제목은 패키지 이름이 길어 72자 제한에서 제외합니다.
본문과 리뷰는 한국어로 씁니다. PR 제목은 squash 후 `main`의 커밋 제목이 됩니다.

| 대상 | 예 |
| --- | --- |
| 기능 | `feat/17-goal-split` · `feat(ios): add goal split card` |
| 수정 | `fix/18-offline-save` · `fix(api): preserve completed actions` |
| 문서·CI | `docs/agent-guide` · `ci: validate pull request policy` |
| 호환성 변경 | `feat(api)!: change action status contract` |

CI는 PR 제목과 브랜치를 검사합니다. 작업 중 커밋은 같은 형식을 따릅니다.
기존 PR #14의 `chore/initial-monorepo-setup`은 유지보수 형식으로 유효합니다.

## 피처 플래그

플래그 기준 파일은 [config/feature-flags.json](../config/feature-flags.json)입니다.
현재 등록된 기능은 없습니다. 이 파일은 메타데이터 계약입니다. 앱의 실행 제어를 대신하지 않습니다.
첫 플래그 기능을 구현할 때 해당 플랫폼과 API의 기본값·OFF 경로를 함께 연결합니다.
첫 버전은 코드와 함께 배포하는 정적 플래그를 사용합니다. 원격 관리 서비스는 필요가 생길 때 결정합니다.

미완성 기능의 항목 예:

```json
{
  "key": "goal_resplitting",
  "default": false,
  "phase": "development",
  "owner": "minjunkim-dev",
  "issue": 17,
  "remove_by": "2026-11-03"
}
```

플래그 이름은 `snake_case`입니다. 담당자, Issue, 제거 기한을 필수로 기록합니다.
`development` 단계에서는 기본값을 `false`로 유지합니다. 플래그가 없거나 값이 잘못되면 OFF로 처리합니다.
로컬 검증만 ON으로 실행합니다. 사용자에게 켜기 전에는 완료 조건, 기기 검증, 롤백 방법을 확인합니다.
출시 승인 Issue를 기록하고 `phase: released`, `default: true`로 바꿉니다.
출시가 안정되면 별도 PR로 플래그와 이전 경로를 제거합니다. 기한을 넘기면 제거하거나 이유와 새 기한을 기록합니다.

OFF 상태에서도 데이터 마이그레이션은 호환되어야 합니다. 인증과 권한 검사는 항상 적용합니다.
PR에는 OFF의 기존 동작, ON의 새 동작, 오류·저장·복구 경로를 기록합니다.

## Issue와 PR

Issue 템플릿으로 기능, 문제, 결정을 구분합니다. 부족한 조건은 질문으로 남깁니다.
의존 Issue를 연결합니다. 구현 담당자는 자신을 지정하고 착수 댓글을 남깁니다.
`decision` 또는 `wayfinder:grilling` Issue의 제품 답은 사람이 확정합니다.
자동 리뷰가 추천했다는 사실로 결정 Issue를 종료하지 않습니다.

PR은 한 목적과 작은 검증 가능한 범위를 가집니다. 문제와 변경 후 동작을 먼저 적습니다.
완료 조건, 검사 결과, UI 근거, 미확인 범위, 플래그 상태를 기록합니다.
Issue를 해결했을 때만 `Closes #번호`를 사용합니다. 부분 변경은 `Refs #번호`를 사용합니다.

자동화는 [REPOSITORY_SETUP](REPOSITORY_SETUP.md)에 정의합니다.
CI 통과와 최신 SHA의 리뷰 응답을 확인합니다. P0/P1 결함은 해결합니다.
P2는 수정하거나 후속 Issue를 연결하고 병합 이유를 기록합니다.
봇의 완료 댓글은 사람의 최종 확인을 대신하지 않습니다.
1인 개발에서는 본인 PR에 다른 사람의 승인을 필수로 요구하지 않습니다.

## 검증과 문서 관리

모든 변경의 최소 검사:

```sh
python3 scripts/check_repository.py
python3 scripts/workflow_policy.py
python3 -m unittest discover -s scripts -p 'test_*.py'
git diff --check
```

워크플로는 `actionlint`로 검사합니다. 기능별 lint·테스트·빌드는 해당 실행 문서를 따릅니다.
화면은 실제 변경한 기기 흐름을 확인합니다. AI는 고정된 예시의 의미와 실행 가능성을 평가합니다.
자동 검사, 빌드, 기기 사용, AI 품질, 업로드, 운영 배포는 각각 다른 증거입니다.

README는 문서 입구와 구현 상태만 설명합니다. AGENTS는 작업 지침을 설명합니다.
CONTRIBUTING과 CLAUDE는 기준 문서를 참조합니다. 제품·보안·실행·검증 문서는 목적이 달라 유지합니다.
`work/`의 검토안은 확정 사양이 아닙니다. 확정 답은 Issue에 남기고 관련 문서에서 연결합니다.

공개 범위와 main 보호의 현재 적용 상태는 [자동화 설정](REPOSITORY_SETUP.md#현재-제한)을 참조합니다.
PR·검사·리뷰 절차를 준수합니다. 저장소를 임의로 공개하거나 요금제를 변경하지 않습니다.

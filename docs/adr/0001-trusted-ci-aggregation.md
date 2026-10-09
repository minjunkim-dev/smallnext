---
status: accepted
---

# CI 집계를 독립된 병합 판단 근거로 분리한다

PR의 workflow는 집계 호출과 입력을 바꿀 수 있습니다.
기준 브랜치의 별도 workflow가 GitHub API의 실제 실행 결과를 검증하도록 설계합니다.
사람 또는 사용자가 작업을 맡긴 로컬 에이전트가 해당 workflow의 실행 ID와 결과를 병합 전에 확인합니다.
기존 필수 검사와 현재 SHA의 소스 리뷰를 함께 확인합니다.

첫 도입은 같은 저장소의 PR을 대상으로 합니다.
플랫폼 검사 정의의 충분성은 소스 리뷰로 확인합니다.
독립 GitHub App과 새 게시 자격 증명은 첫 도입에 포함하지 않습니다.
이 선택은 외부 설정 없이 집계 입력의 신뢰를 개선합니다.
같은 GitHub Actions App에서 검사 이름을 위조하는 PR을 보호 설정이 자동으로 차단한다는 보장은 제공하지 않습니다.
fork PR 지원과 필수 검사 출처의 독립 강제는 후속 범위입니다.

2026-10-09 사용자가 추천안으로 설계를 확정했습니다.
확정 답, 실패 정책, 도입 순서와 완료 조건은 [Issue #83의 설계 확정 답](https://github.com/minjunkim-dev/smallnext/issues/83#issuecomment-6078139109)에 있습니다.
이 ADR은 설계 결정입니다. 집계 workflow의 구현과 실제 도입 검증은 아직 완료하지 않았습니다.

근거: [GitHub 필수 검사 출처](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-status-checks-before-merging), [workflow 이벤트의 실행 컨텍스트](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).

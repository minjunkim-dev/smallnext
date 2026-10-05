# Issue tracker: GitHub

Smallnext의 Issue와 구현 사양은 `minjunkim-dev/smallnext`의 GitHub Issues에서 관리한다.
모든 Issue·PR 작업은 `gh` CLI를 사용한다. 저장소는 `git remote -v`로 확인한다.

## 기본 작업

- Issue 생성: 여러 줄 본문은 파일로 준비하고 `gh issue create --repo minjunkim-dev/smallnext --title "<title>" --body-file <file>`로 게시한다.
- Issue 읽기: `gh issue view <number> --repo minjunkim-dev/smallnext --comments`로 질문과 확정 답을 확인한다.
- 라벨 적용: 역할 이름은 [triage-labels.md](triage-labels.md)의 실제 라벨을 사용한다.
- Issue 게시를 요구하는 skill은 GitHub Issue를 만든다. `.scratch/`의 로컬 Issue로 대체하지 않는다.
- 제품 결정은 해당 Issue의 해결 댓글에 기록한다. [WORKFLOW](../WORKFLOW.md)의 사람 확인·PR·병합 규칙을 따른다.

## Pull requests as a triage surface

**PRs as a request surface: no.**

외부 PR을 자동으로 triage 입력에 포함하지 않는다. 이 범위를 바꾸려면 위 값을 명시적으로 변경한다.
GitHub는 Issue와 PR의 번호를 공유한다. 대상이 모호하면 `gh pr view <number>`와 `gh issue view <number>`로 종류를 확인한다.

## Wayfinding operations

- Map: `wayfinder:map` 라벨을 사용한다. 지도에는 Destination·Notes·Decisions so far·Not yet specified·Out of scope를 기록한다.
- Child ticket: GitHub sub-issue로 지도에 연결한다. `wayfinder:research`·`wayfinder:prototype`·`wayfinder:grilling`·`wayfinder:task` 중 하나를 적용한다.
- Claim: 작업의 첫 쓰기로 `gh issue edit <number> --repo minjunkim-dev/smallnext --add-assignee @me`를 실행한다. 이미 할당된 열린 질문은 다른 세션의 작업으로 보존한다.
- Blocking: GitHub native issue dependencies를 사용한다. `gh api --method POST repos/minjunkim-dev/smallnext/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`로 연결한다. `issue_id`는 Issue 번호나 node ID가 아닌 숫자 database ID이다.
- Frontier: 지도의 열린 sub-issue를 조회한다. `issue_dependencies_summary.blocked_by == 0`이고 미할당인 첫 질문을 지도 순서대로 선택한다.
- Resolve: 실제 확정 답을 해결 댓글로 게시한다. 질문을 닫는다. 지도의 Decisions so far에는 제목 링크와 한 줄 요약만 추가한다.

native sub-issue나 dependency가 없는 tracker로 바꾸면 해당 대체 규칙을 이 문서에 기록한다. GitHub에서 사용할 수 있는 native 관계를 본문 목록으로 대체하지 않는다.

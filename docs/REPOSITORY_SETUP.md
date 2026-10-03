# 저장소와 AI 자동화 설정

확인 날짜: 2026-10-03, Asia/Seoul.

## 생성과 병합

- 저장소: [minjunkim-dev/smallnext](https://github.com/minjunkim-dev/smallnext).
- 공개 범위: private.
- 기본 브랜치: main.
- 병합 방식: squash만 허용.
- 병합 후 작업 브랜치 자동 삭제: 사용.
- Issue: 사용. Wiki, Discussions, 저장소 Projects: 사용하지 않음.
- 외부 협업자는 추가하지 않음.

## 자동 작업과 사람의 작업

| 작업 | 담당과 실행 조건 |
| --- | --- |
| 문서 링크·공백·Action SHA·플래그 메타데이터 | Repository checks. main push와 PR마다 실행 |
| PR 제목·브랜치·구현 Issue 연결 | PR policy. PR 생성·수정·새 커밋마다 실행 |
| Issue의 범위·완료 조건·선행 조건 검토 | Claude. 쓰기 권한 사용자가 Issue 생성·수정 또는 `ai:review` 라벨 지정 |
| PR의 회귀·플래그·보안 검토와 댓글 | Claude. main 대상 PR 생성·갱신·ready 전환. Draft와 fork는 제외 |
| 코드 리뷰와 보안 리뷰 | Codex GitHub 연결. 자동 리뷰 옵션은 계정 설정에서 활성화 |
| 제품 결정·계정 연결·기기 확인·최종 병합 | 사람. AI는 검토안을 제시하고 승인된 구현을 수행 |

Claude 재검토는 댓글 첫 줄에 `@claude review` 또는 `@claude security review`를 씁니다.
`ai:review` 라벨을 제거한 후 다시 지정해도 재검토합니다. `ai:skip`은 Claude 자동 리뷰를 중지합니다.
봇 이벤트는 재실행하지 않습니다. 같은 대상의 이전 리뷰 실행은 새 요청이 취소합니다.
동일 이벤트의 반복 검토가 필요하면 Actions의 `Claude issue and PR review`를 수동 실행합니다.

Claude는 작업별 GitHub 토큰을 사용합니다. 댓글 작성자는 `github-actions[bot]`으로 표시됩니다.
코드 쓰기와 병합 권한은 없습니다. `@claude implement`는 이 워크플로의 지원 명령이 아닙니다.
구현은 승인된 Issue를 로컬 Claude Code/Codex에 전달합니다. Codex 원격 작업은 별도 환경 연결 후 사용합니다.
Secret 미등록은 실행 실패로 표시합니다. 리뷰가 수행된 것으로 처리하지 않습니다.

Codex 수동 요청은 PR에서 `@codex review`, `@codex security review`를 사용합니다.
자동 리뷰 여부는 Codex 계정 설정으로 관리합니다. 저장소 YAML만으로 연결을 완료했다고 판단하지 않습니다.
GitHub Actions 토큰이 쓴 댓글은 다른 워크플로의 트리거가 되지 않을 수 있습니다.
따라서 Actions로 Codex 멘션을 자동 게시하는 우회 방식은 사용하지 않습니다.

## CI와 업데이트

- main push와 main 대상 PR에서 Repository checks를 실행합니다.
- Repository hygiene 검사는 UTF-8, 줄 끝, 공백, 로컬 문서 링크, Action 커밋 고정을 확인합니다.
- CI 기본 권한은 read입니다. 자동 승인 기능은 사용하지 않습니다.
- 기본 허용 Action은 GitHub 공식 소유 Action입니다. Claude 리뷰에 필요한 검토한 SHA만 예외로 추가합니다.
- 저장소 정책에서 Action 전체 커밋 SHA 고정을 요구합니다.
- Dependabot은 GitHub Actions 업데이트를 매주 확인합니다.
- Dependabot 취약점 알림과 자동 보안 수정 기능을 켰습니다.

새 앱 의존성이 생기면 해당 패키지 관리자도 Dependabot 설정에 추가합니다.
외부 Action이 필요하면 출처와 권한을 검토한 뒤 허용 범위를 수정합니다.

## Action 허용 목록

GitHub 소유 Action 허용과 SHA 고정은 유지합니다. 다음 두 항목만 예외로 추가합니다.

| Action | 허용 SHA |
| --- | --- |
| `anthropics/claude-code-action` | `12dd8d74c712f5f3669365b2369b558c495b1104` |
| `oven-sh/setup-bun` | `0c5077e51419868618aeaa5fe8019c62421857d6` |

Bun 설치 Action은 고정된 Claude composite Action이 내부에서 사용합니다.
Dependabot이 새 SHA를 제안하면 출처와 내부 Action 변경을 확인한 후 허용 목록도 갱신합니다.

## 최초 연결: 수동 설정

이 작업에는 계정 로그인과 Secret 등록이 필요합니다. Secret 값은 채팅이나 문서에 기록하지 않습니다.

1. 로컬 Claude Code에서 `claude setup-token`을 실행합니다. 발급 값을 Smallnext의 Actions Secret `CLAUDE_CODE_OAUTH_TOKEN`으로 등록합니다. GitHub 토큰이나 운영 API 키는 사용하지 않습니다.
2. GitHub Actions의 허용 목록에 검토한 `anthropics/claude-code-action`과 필요한 내부 Action의 전체 SHA를 추가합니다. 전체 Action 허용으로 바꾸지 않습니다.
3. Codex GitHub 연결의 저장소 접근 범위에 `minjunkim-dev/smallnext`를 추가합니다. Code review 설정에서 해당 저장소의 Automatic review를 켭니다.
4. Security review의 자동 실행 옵션이 있으면 켭니다. 옵션이 없거나 권한이 없으면 PR마다 사람이 `@codex security review`를 요청하고 응답을 확인합니다.
5. 이 PR을 main에 병합한 후 새 Issue와 작은 PR로 첫 실행을 확인합니다. 실행 URL, 봇 댓글 URL, 검토 SHA를 아래 표에 기록합니다.

Claude Action은 GitHub App 대신 작업 토큰을 사용하므로 Claude GitHub App 설치는 필수가 아닙니다.
Secret과 코드 리뷰 구독·요금은 별도 조건입니다. 일반 ChatGPT API 키는 Codex GitHub 연결을 대신하지 않습니다.

공식 기준: [Claude GitHub Actions](https://code.claude.com/docs/en/github-actions),
[Claude Action 보안](https://github.com/anthropics/claude-code-action/blob/12dd8d74c712f5f3669365b2369b558c495b1104/docs/security.md),
[Codex GitHub 리뷰](https://developers.openai.com/codex/cloud/code-review/).

## 현재 제한

현재 계정 요금제에서는 비공개 저장소의 브랜치 ruleset을 사용할 수 없습니다.
GitHub가 활성 main 보호 규칙 생성 요청을 HTTP 403으로 거절했습니다.
따라서 PR 필수, CI 통과 필수, main 강제 푸시와 삭제 차단은 기술적으로 강제되지 않습니다.
[협업 방법](WORKFLOW.md)의 PR 절차를 작업 규칙으로 사용합니다.

향후 비공개 저장소 보호를 지원하는 요금제를 사용하면 main 보호 규칙을 추가합니다.
PR과 Repository hygiene 검사를 요구하고 강제 푸시와 삭제를 차단합니다.
현재 1인 개발에서는 다른 사람의 승인을 필수로 요구하지 않습니다.

## 연결 상태와 검증 근거

2026-10-03 조사 결과입니다. 실제 연결과 첫 실행은 별도로 확인합니다.

| 항목 | 상태와 근거 |
| --- | --- |
| main·squash·병합 후 브랜치 삭제 | GitHub API로 설정 확인 |
| main 보호 | rulesets API HTTP 403. 작업 규칙만 적용 |
| Action 허용 목록·리뷰 라벨 | 고정 SHA 두 개와 `ai:review`·`ai:skip`을 저장하고 API로 재확인 |
| Claude 인증 | 최초 조사에서 Secret 없음. 등록과 실제 실행 대기 |
| Codex 저장소 접근·자동 코드/보안 리뷰 | 계정 설정 확인 대기. 봇 응답 미검증 |
| 이번 변경의 CI·리뷰 실행 | PR의 최종 SHA 검사 결과와 댓글로 기록 |

브라우저 도구가 작업 경로의 심볼릭 링크 때문에 시작되지 않아 계정 설정을 직접 확인하지 못했습니다.
PR 생성·CI 통과는 Secret 등록, 계정 연결, AI 응답을 증명하지 않습니다.
기능 플래그는 메타데이터 계약만 추가했습니다. 앱에서 실제 OFF·ON 경로를 구현한 증거는 없습니다.

이번 작업의 연결·검증 후속 상태는 [Issue #15](https://github.com/minjunkim-dev/smallnext/issues/15)에 기록합니다.

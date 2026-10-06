# 저장소와 AI 자동화 설정

설정 확인 날짜: 2026-10-04, Asia/Seoul. 아래 과거 봇 실행 기록의 확인 날짜는 별도로 표시합니다.

## 생성과 병합

- 저장소: [minjunkim-dev/smallnext](https://github.com/minjunkim-dev/smallnext).
- 공개 범위: public. 2026-10-04 전환 후 GitHub API로 확인.
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
| Issue의 범위·완료 조건·선행 조건 검토 | Claude. 수동 호출만. 쓰기 권한 사용자가 `ai:review` 라벨 지정 또는 리뷰 댓글 작성 |
| PR의 회귀·플래그·보안 검토와 댓글 | Claude. 수동 호출만. main 대상 PR에 `ai:review` 라벨 지정 또는 리뷰 댓글 작성. Draft와 fork는 제외 |
| 코드 리뷰와 보안 리뷰 | Codex. 모든 PR을 매 푸시마다 코드 검토하고 보안 검토도 함께 실행 |
| 제품 결정·계정 연결·기기 확인 | 사람. AI는 검토안을 제시하고 승인된 구현을 수행 |
| 병합 | [병합 조건](WORKFLOW.md#병합-조건)을 충족하면 작업을 맡은 로컬 에이전트 또는 사람. 리뷰 봇은 병합하지 않음 |

Claude 검토는 댓글 첫 줄에 `@claude review` 또는 `@claude security review`를 씁니다. Issue·PR 생성과 push는 Claude를 실행하지 않습니다.
`ai:review` 라벨을 제거한 후 다시 지정해도 재검토합니다. `ai:skip` 항목은 Claude가 검토하지 않습니다.
봇 이벤트는 재실행하지 않습니다. 같은 PR head 또는 같은 Issue의 이전 리뷰 작업은 권한 확인을 통과한 새 요청만 취소합니다.
읽기 전용 권한 확인, Secret을 사용하는 모델 검토, 댓글 게시 작업을 분리합니다.
봇 댓글·일반 댓글·거절된 요청은 실행 중인 리뷰를 취소하지 않습니다.
PR의 그룹 키에 검토 SHA를 포함합니다. 오래된 head의 권한 확인이 늦게 끝나도 새 head의 리뷰를 취소하지 않습니다.
반복 검토는 Issue·PR에 `@claude review` 또는 `@claude security review` 댓글로 요청합니다. 임의 브랜치의 수동 workflow dispatch는 지원하지 않습니다. 세 작업은 main의 신뢰된 코드만 실행합니다.

Claude 모델 작업은 읽기 전용 GitHub 토큰을 사용합니다. 신뢰된 Python 코드가 제한된 Issue·PR 자료와 diff를 준비합니다.
PR의 Refs·Closes 등으로 연결한 같은 저장소의 Issue를 최대 3개 읽습니다. 연결된 기획 문서는 신뢰된 checkout의 추적된 docs/ Markdown에서만 가져옵니다.
문서는 최대 6개·합계 48,000자로 제한합니다. 외부 링크·다른 Git ref·디렉터리 탈출·추적되지 않은 파일은 읽지 않습니다. 자료 누락과 잘림을 보고합니다.
모델의 파일·셸·MCP 도구를 모두 비활성화합니다. 모델은 제공된 자료만 검토하고 댓글을 직접 게시하지 않습니다.
초기화 기록의 도구·MCP 목록이 비어 있는지 검사합니다. 도구 호출이 있거나 초기화 기록이 없으면 게시하지 않습니다.
성공한 최종 응답의 길이와 인증정보 형식을 검사하고 대상 번호·SHA에 묶습니다. 별도 게시 작업만 댓글 쓰기 권한을 받습니다.
게시 직전에 현재 head SHA와 대상 상태를 다시 확인합니다. 변경되면 게시하지 않습니다. 댓글 작성자는 `github-actions[bot]`으로 표시됩니다.
Issue는 검토한 제목·본문·댓글의 SHA-256을 보고서에 묶습니다. 게시 직전 자료가 다르면 게시하지 않습니다.
PR 메타데이터·연결 Issue·기획 자료는 수집 시점의 기록입니다. 현재 head 검사가 이 자료의 최신성까지 보증하지 않습니다. 완료 조건을 커밋 없이 바꿨다면 사람이 PR 재검토를 요청합니다.
모델 출력의 멘션은 무력화하여 다른 사용자나 팀에 알림을 보내지 않습니다.
하위 프로세스의 인증 환경 변수 제거를 활성화합니다. 전체 모델·도구 출력은 로그에 표시하지 않습니다.
검토 자료는 권한 0600의 runner 임시 파일로 전달합니다. SDK 전용 `base-action`을 사용하며 Action 입력·로그에는 파일 경로만 넣습니다. 검토 자료를 출력하는 상위 Action의 `prompt` 입력은 사용하지 않습니다.
CI는 Ubuntu 패키지 저장소에서 `bubblewrap`·`socat`을 설치하고 사용자 네임스페이스 격리 실행을 확인합니다.
Ubuntu 24.04의 AppArmor 제한이 켜져 있으면 `/usr/bin/bwrap`에만 사용자 네임스페이스 생성 권한을 부여합니다.
시스템 전체의 AppArmor 정책과 네임스페이스 제한은 유지합니다.
실패 시 SDK의 구조화된 오류 코드와 종료 상태에서 고정된 분류만 보고합니다.
모델 답변과 자유 형식 오류 문구는 원인 분류에 사용하지 않습니다. 모델 메시지와 토큰 값은 출력하지 않습니다.
격리 도구가 없으면 실행을 실패로 처리합니다. 인증 환경 변수 제거를 끄는 우회는 사용하지 않습니다.
코드 쓰기와 병합 권한은 없습니다. 저장소의 Actions PR 자동 승인 설정도 꺼진 상태인지 확인합니다.
`@claude implement`는 이 워크플로의 지원 명령이 아닙니다.
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
| `anthropics/claude-code-action/base-action` | `97c53473391bff1901034d4b454b5bac7ab7a029` |
| `oven-sh/setup-bun` | `0c5077e51419868618aeaa5fe8019c62421857d6` |

Bun 설치 Action은 고정된 Claude composite Action이 내부에서 사용합니다.
Dependabot이 새 SHA를 제안하면 출처와 내부 Action 변경을 확인한 후 허용 목록도 갱신합니다.

## 최초 연결: 수동 설정

이 작업에는 계정 로그인과 Secret 등록이 필요합니다. Secret 값은 채팅이나 문서에 기록하지 않습니다.

1. 로컬 Claude Code에서 `claude setup-token`을 실행합니다. 발급 값을 Smallnext의 Actions Secret `CLAUDE_CODE_OAUTH_TOKEN`으로 등록합니다. GitHub 토큰이나 운영 API 키는 사용하지 않습니다.
2. GitHub Actions의 허용 목록에 검토한 `anthropics/claude-code-action/base-action`과 필요한 내부 Action의 전체 SHA를 추가합니다. 전체 Action 허용으로 바꾸지 않습니다.
3. Codex GitHub 연결에서 `minjunkim-dev/smallnext` 접근을 허용합니다. 해당 저장소의 자동 코드 검토를 `Review all PRs`, 검토 트리거를 `Every push`로 설정합니다.
4. 자동 보안 검토를 `Review all PRs`, 트리거를 `Whenever code review runs`로 설정합니다. 자동 보고는 Critical·High, 수동 보고는 Critical·High·Medium을 유지합니다. 위협 모델 경로를 비우면 검토마다 모델을 생성합니다.
5. 워크플로를 main에 병합한 후 Issue와 작은 PR로 첫 실행을 확인합니다. 실행 URL, 봇 댓글 URL, 검토 SHA를 아래 표에 기록합니다.

Claude Action은 GitHub App 대신 작업 토큰을 사용하므로 Claude GitHub App 설치는 필수가 아닙니다.
Secret과 코드 리뷰 구독·요금은 별도 조건입니다. 일반 ChatGPT API 키는 Codex GitHub 연결을 대신하지 않습니다.

토큰 갱신 담당자는 저장소 소유자입니다. 발급 시 만료일을 확인하고 값은 기록하지 않습니다.
HTTP 401 또는 SDK `authentication_failed`가 발생하면 해당 리뷰를 미검증으로 표시합니다.
`claude setup-token`으로 새 OAuth 토큰을 발급하고 Actions Secret을 교체한 뒤 main에서 다시 검토합니다.
재등록 후에는 실행 성공과 실제 봇 댓글을 모두 확인합니다. PR 댓글의 검토 SHA가 현재 head와 같은지도 확인합니다.
인증 장애 중에는 Claude 리뷰를 미검증으로 기록합니다. 병합은 Codex 결과로 [병합 조건](WORKFLOW.md#병합-조건)을 확인한 후 진행합니다. 봇은 승인하거나 병합하지 않습니다.

공식 기준: [Claude GitHub Actions](https://code.claude.com/docs/en/github-actions),
[Claude Linux 격리 설정](https://code.claude.com/docs/en/sandboxing#set-up-linux-and-wsl2),
[Claude Action 보안](https://github.com/anthropics/claude-code-action/blob/97c53473391bff1901034d4b454b5bac7ab7a029/docs/security.md),
[Codex GitHub 리뷰](https://developers.openai.com/codex/cloud/code-review/).

## 현재 제한

2026-10-04 공개 전환 전에 기존 Claude 워크플로를 일시 중지했습니다.
이번 도구 없는 리뷰·별도 게시 방식은 main 반영 뒤 다시 켭니다. 실행 성공, 초기화 검증과 현재 SHA의 댓글을 확인합니다.
아래 과거 실행 기록은 이전 방식의 증거입니다. 이번 방식의 GitHub 런타임 검증은 아직 완료하지 않았습니다.

공개 전환 후 main 보호를 적용하고 API로 확인했습니다. PR과 최신 기준 브랜치의 검사를 요구합니다.
필수 검사 이름은 `PR conventions`, `Repository hygiene`, `Project checks`입니다.
관리자에게도 규칙을 적용합니다. 선형 이력, 미해결 리뷰 대화 해결, 강제 push·main 삭제 금지를 요구합니다.
현재 1인 개발에서는 다른 사람의 승인을 필수로 요구하지 않습니다. [협업 방법](WORKFLOW.md)의 사람 병합 규칙은 유지합니다.
비공개일 때 ruleset 요청이 HTTP 403으로 거절된 기록은 현재 공개 저장소의 보호 상태를 나타내지 않습니다.

## 연결 상태와 검증 근거

2026-10-03 확인 결과입니다. 계정 설정 저장과 실제 봇 응답을 구분합니다.

| 항목 | 상태와 근거 |
| --- | --- |
| main·squash·병합 후 브랜치 삭제 | GitHub API로 설정 확인 |
| main 보호 | rulesets API HTTP 403. 작업 규칙만 적용 |
| Action 허용 목록·리뷰 라벨 | 고정 SHA 두 개와 `ai:review`·`ai:skip`을 저장하고 API로 재확인 |
| Claude 인증·실행 | OAuth Secret 재등록 후 main의 [Issue 검토 실행](https://github.com/minjunkim-dev/smallnext/actions/runs/37126902068) 성공. 토큰 값은 읽거나 기록하지 않음 |
| Claude Issue 실제 응답 | [Issue #15 검토 댓글](https://github.com/minjunkim-dev/smallnext/issues/15#issuecomment-5969716401) 게시 확인. 워크플로 기준 커밋 `1eaf836afd9f0c8c65978192f30e1f78c0ddedd1` |
| Claude PR 일반 검토·CI 조회 | [PR #27 검토 실행](https://github.com/minjunkim-dev/smallnext/actions/runs/37127614521) 성공. [실제 리뷰 댓글](https://github.com/minjunkim-dev/smallnext/pull/27#issuecomment-5969819982)의 검토 SHA `3932a2512f28a5c40ddf6a495657d3b103a95b6c` 확인. 최소 읽기 권한 추가 후 CI 결과 조회 성공 |
| Claude PR 보안 명령 | [`@claude security review` 요청](https://github.com/minjunkim-dev/smallnext/pull/27#issuecomment-5969832224) 뒤 [실행](https://github.com/minjunkim-dev/smallnext/actions/runs/37127780558) 성공. [보안 검토 댓글](https://github.com/minjunkim-dev/smallnext/pull/27#issuecomment-5969841220)의 검토 SHA `3932a2512f28a5c40ddf6a495657d3b103a95b6c` 확인. P2 취소 경합 지적은 후속 변경에서 그룹 키에 SHA를 추가해 수정 |
| Codex 저장소 접근 | GitHub 앱 설치 화면과 Codex 저장소 목록에서 Smallnext 접근 확인 |
| Codex 자동 코드 리뷰 | 계정 설정에 모든 PR 검토·매 푸시마다 실행 저장 확인 |
| Codex 자동 보안 리뷰 | 계정 설정에 모든 PR 검토·코드 리뷰와 함께 실행 저장 확인. 자동 보고 Critical·High, 수동 보고 Critical·High·Medium |
| main 병합·CI | [PR #18](https://github.com/minjunkim-dev/smallnext/pull/18)을 squash 병합. 커밋 `1eaf836afd9f0c8c65978192f30e1f78c0ddedd1`의 [저장소 검사](https://github.com/minjunkim-dev/smallnext/actions/runs/37126498060)와 [프로젝트 검사](https://github.com/minjunkim-dev/smallnext/actions/runs/37126498353) 통과 |
| Codex 실제 응답 | [PR #18 봇 응답](https://github.com/minjunkim-dev/smallnext/pull/18#issuecomment-5969297999)에서 최종 자동 코드·보안 리뷰 완료 확인. 검토 SHA `78ceee101164c9d768a24e50700092f717e4e06a`. 기존 지적 2건 수정 후 새 지적 없음 |
| 앱·API 초기 셋업과 캐시 검증 | [PR #14 검사](https://github.com/minjunkim-dev/smallnext/pull/14/checks). 커밋 `2ab3841`의 [첫 실행](https://github.com/minjunkim-dev/smallnext/actions/runs/37118733750/attempts/1)과 [캐시 복원 실행](https://github.com/minjunkim-dev/smallnext/actions/runs/37118733750/attempts/2)에서 앱·API 테스트 통과 |

브라우저 재시작과 GitHub 본인 인증 후 계정 설정을 확인했습니다.
PR 생성·CI 통과는 Secret 등록, 계정 연결, AI 응답을 증명하지 않습니다.
기능 플래그는 메타데이터 계약만 추가했습니다. 앱에서 실제 OFF·ON 경로를 구현한 증거는 없습니다.
실제 fork PR의 권한 거절 실행은 확인하지 않았습니다. 거절 조건은 단위 테스트와 워크플로 소스로 확인했습니다.
워크플로 변경을 시험한 실행과 main 실행을 구분합니다. 병합 전에는 현재 head의 리뷰 댓글과 CI도 다시 확인합니다.

이번 작업의 연결·검증 후속 상태는 [Issue #15](https://github.com/minjunkim-dev/smallnext/issues/15)에 기록합니다.

Project checks는 iOS·Android·API와 컨테이너를 검사합니다.
로컬 실행은 [개발 환경](DEVELOPMENT.md), 캐시와 병렬 실행은 [CI 구성](CI.md)을 따릅니다.
실제 AI 품질과 운영 배포는 초기 셋업의 검증 범위에 포함하지 않습니다.

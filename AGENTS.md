# Smallnext 작업 지침

이 파일은 사람, Claude Code, Codex의 공통 길잡이입니다.
프로젝트 지침은 이 파일에서만 안내합니다. 도구별 지침 파일을 만들지 않습니다.

## 구현 길잡이

- 작업 시작: [README](README.md)에서 구현 상태를 확인하고 [협업 규칙](docs/WORKFLOW.md)을 읽습니다. 다른 작업자의 변경을 보존합니다.
- 제품 사양: 관련 Issue의 확정 답·완료 조건과 연결한 문서를 읽습니다. [미결정 항목](docs/DECISIONS.md)은 사람이 확정합니다.
- 도메인: [문서 길잡이](docs/agents/domain.md)를 따라 `CONTEXT.md`와 관련 ADR을 확인합니다.
- 검증·플래그: [협업 규칙](docs/WORKFLOW.md)의 검증 명령·피처 플래그·문서 관리 기준을 따릅니다.
- 권리·외부 자산: [COPYRIGHT](COPYRIGHT.md)와 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)를 확인합니다.

## 독립 리뷰와 병합

리뷰 에이전트는 [코딩 규칙](docs/coding-standards.md)과 [로컬 독립 리뷰](docs/agents/review.md)를 읽습니다. 코딩 규칙은 구현 컨텍스트에 일괄 주입하지 않습니다.
맡긴 `two-way/narrow` 작업은 최종 독립 리뷰·필수 CI·완료 조건 통과 후 병합합니다. `one-way/broad`는 사람이 최종 head를 승인합니다. 자세한 조건은 [병합 정책](docs/WORKFLOW.md#병합-조건)을 따릅니다.
자동화 연결·실행 근거는 [자동화 설정](docs/REPOSITORY_SETUP.md)을 확인합니다.

## Agent skills

- Issue tracker: GitHub `minjunkim-dev/smallnext`. `docs/agents/issue-tracker.md`를 읽습니다.
- Triage labels: `docs/agents/triage-labels.md`에서 다섯 역할과 라벨을 확인합니다.
- Domain docs: [문서 길잡이](docs/agents/domain.md)를 따릅니다.

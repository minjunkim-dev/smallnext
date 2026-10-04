# Smallnext

큰 목표를 지금 실행할 수 있는 작은 다음 행동으로 바꾸는 플래너입니다.

## 현재 상태

제품 기획과 초기 구현 환경을 준비한 단계입니다.
iOS·Android 기본 앱, 로컬 DB 초기화, Rust API, 개발 DB와 CI 구성을 추가했습니다.
공통 작업 지침과 에이전트 리뷰 워크플로도 저장소에서 관리합니다.
제품 기능, 실제 AI 연결, 인증·동기화, 운영 배포는 아직 구현하지 않았습니다.

## 제품 방향

- 사용자가 최종 목표를 입력합니다.
- 실행 화면에는 현재 행동 하나를 표시합니다.
- 현재 행동이 어려우면 더 작은 행동으로 나눕니다.
- 완료한 행동을 기록하고 다음 행동을 제시합니다.
- 최종 목표와 완료 이력은 앱이 보존합니다.

Smallnext는 '작은 다음 행동'을 나타내는 작업 이름입니다.
공식 출시 이름과 상표 검토는 별도로 결정합니다.

## 시작하기

1. [공통 작업 지침](AGENTS.md)을 읽습니다. Claude Code는 `CLAUDE.md`에서 같은 지침을 가져옵니다.
2. [개발 환경과 실행](docs/DEVELOPMENT.md)에 따라 필요한 프로젝트를 실행합니다.
3. [결정 지도 #2](https://github.com/minjunkim-dev/smallnext/issues/2)에서 확정 답과 다음 질문을 확인합니다.
4. [협업 규칙](docs/WORKFLOW.md)에 따라 짧은 브랜치와 작은 PR을 사용합니다.

기본 검사는 Python 3 표준 라이브러리만 사용합니다.

```sh
python3 scripts/check_repository.py
python3 scripts/workflow_policy.py
python3 -m unittest discover -s scripts -p 'test_*.py'
```

이 검사는 저장소 파일의 기본 상태를 확인합니다. 앱의 작동이나 AI 품질을 증명하지 않습니다.

## 문서

| 문서 | 기준 정보 |
| --- | --- |
| [AGENTS](AGENTS.md) | 모든 AI 에이전트의 작업과 리뷰 지침 |
| [WORKFLOW](docs/WORKFLOW.md) | trunk-based 개발, 이름, Issue·PR, 피처 플래그 |
| [DEVELOPMENT](docs/DEVELOPMENT.md) | 플랫폼별 개발 환경과 실행 명령 |
| [CI](docs/CI.md) | 캐시, 병렬 실행, 변경 범위에 따른 검사 선택 |
| [SETUP_VALIDATION](docs/SETUP_VALIDATION.md) | 초기 앱·API 셋업의 검증 범위와 근거 |
| [REPOSITORY_SETUP](docs/REPOSITORY_SETUP.md) | 자동화, 계정 연결, 현재 제한과 실행 증거 |
| [CONTEXT](CONTEXT.md) | 진행 상태, 입력 초안, 완료·보류·중단·삭제의 용어 |
| [PRODUCT](docs/PRODUCT.md) · [DECISIONS](docs/DECISIONS.md) | 제품 가설과 미결정 항목. 확정 답은 해당 Issue |
| [SECURITY](SECURITY.md) | 비밀정보 처리와 비공개 문제 보고 |
| [CONTRIBUTING](CONTRIBUTING.md) | 기여를 시작할 때 확인할 기준 문서 |

작업 절차를 별도 문서에 복제하지 않습니다. 앱 셋업 문서는 실행·CI·검증 근거만 관리합니다.

공개 라이선스는 아직 선택하지 않았습니다.

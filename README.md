# Smallnext

큰 목표를 지금 실행할 수 있는 작은 다음 행동으로 바꾸는 플래너입니다.

## 현재 상태

`main`에는 제품 문서와 저장소 검사가 있습니다.
[PR #14](https://github.com/minjunkim-dev/smallnext/pull/14)에서 iOS·Android 앱과 Rust API의 초기 구성을 준비하고 있습니다.
해당 PR이 병합되기 전에는 `main`에 앱 코드가 없습니다.
제품 기능, 실제 AI 연결, 운영 배포는 완료되지 않았습니다.

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
2. [결정 지도 #2](https://github.com/minjunkim-dev/smallnext/issues/2)에서 확정 답과 다음 질문을 확인합니다.
3. [협업 규칙](docs/WORKFLOW.md)에 따라 짧은 브랜치와 작은 PR을 사용합니다.

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
| [REPOSITORY_SETUP](docs/REPOSITORY_SETUP.md) | 자동화, 계정 연결, 현재 제한과 실행 증거 |
| [PRODUCT](docs/PRODUCT.md) · [DECISIONS](docs/DECISIONS.md) | 제품 가설과 미결정 항목. 확정 답은 해당 Issue |
| [SECURITY](SECURITY.md) | 비밀정보 처리와 비공개 문제 보고 |

작업 절차를 별도 문서에 복제하지 않습니다. 앱 셋업 문서는 실행·CI·검증 근거만 관리합니다.

공개 라이선스는 아직 선택하지 않았습니다.

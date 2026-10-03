# Smallnext

큰 목표를 지금 실행할 수 있는 작은 다음 행동으로 바꾸는 플래너입니다.

## 현재 상태

제품 기획과 초기 구현 환경을 준비한 단계입니다.
iOS·Android 기본 앱, 로컬 DB 초기화, Rust API, 개발 DB와 CI 구성을 추가했습니다.
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

1. [개발 환경과 실행](docs/DEVELOPMENT.md)에 따라 필요한 프로젝트를 실행합니다.
2. [제품 가설](docs/PRODUCT.md)과 [미결정 항목](docs/DECISIONS.md)을 확인합니다.
3. [협업 방법](docs/WORKFLOW.md)에 따라 작은 변경을 PR로 제출합니다.

기본 검사는 Python 3 표준 라이브러리만 사용합니다.

```sh
python3 scripts/check_repository.py
```

이 검사는 저장소 파일의 기본 상태를 확인합니다. 앱의 작동이나 AI 품질을 증명하지 않습니다.

## 문서

- [개발 환경과 실행](docs/DEVELOPMENT.md)
- [초기 셋업 검증 기록](docs/SETUP_VALIDATION.md)
- [제품 가설](docs/PRODUCT.md)
- [미결정 항목](docs/DECISIONS.md)
- [협업 방법](docs/WORKFLOW.md)
- [저장소 초기 설정과 제한](docs/REPOSITORY_SETUP.md)
- [기여 안내](CONTRIBUTING.md)
- [보안 안내](SECURITY.md)

공개 라이선스는 아직 선택하지 않았습니다.

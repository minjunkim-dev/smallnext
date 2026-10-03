# 저장소 초기 설정

확인 날짜: 2026-10-03, Asia/Seoul.

## 생성과 병합

- 저장소: [minjunkim-dev/smallnext](https://github.com/minjunkim-dev/smallnext).
- 공개 범위: private.
- 기본 브랜치: main.
- 병합 방식: squash만 허용.
- 병합 후 작업 브랜치 자동 삭제: 사용.
- Issue: 사용. Wiki, Discussions, 저장소 Projects: 사용하지 않음.
- 외부 협업자는 추가하지 않음.

## CI와 업데이트

- main push와 main 대상 PR에서 Repository checks를 실행합니다.
- Repository hygiene 검사는 UTF-8, 줄 끝, 공백, 로컬 문서 링크, Action 커밋 고정을 확인합니다.
- CI 기본 권한은 read입니다. CI가 PR을 승인할 수 없습니다.
- 기본 허용 Action은 GitHub 공식 소유 Action입니다.
- 저장소 정책에서 Action 전체 커밋 SHA 고정을 요구합니다.
- Dependabot은 GitHub Actions 업데이트를 매주 확인합니다.
- Dependabot 취약점 알림과 자동 보안 수정 기능을 켰습니다.

새 앱 의존성이 생기면 해당 패키지 관리자도 Dependabot 설정에 추가합니다.
외부 Action이 필요하면 출처와 권한을 검토한 뒤 허용 범위를 수정합니다.

## 현재 제한

현재 계정 요금제에서는 비공개 저장소의 브랜치 ruleset을 사용할 수 없습니다.
GitHub가 활성 main 보호 규칙 생성 요청을 HTTP 403으로 거절했습니다.
따라서 PR 필수, CI 통과 필수, main 강제 푸시와 삭제 차단은 기술적으로 강제되지 않습니다.
[협업 방법](WORKFLOW.md)의 PR 절차를 작업 규칙으로 사용합니다.

향후 비공개 저장소 보호를 지원하는 요금제를 사용하면 main 보호 규칙을 추가합니다.
PR과 Repository hygiene 검사를 요구하고 강제 푸시와 삭제를 차단합니다.
현재 1인 개발에서는 다른 사람의 승인을 필수로 요구하지 않습니다.

## 검증 범위

로컬 기본 검사와 GitHub main push 검사가 통과했습니다.
이 문서의 PR에서도 동일 검사가 실행되는지 확인합니다.
앱 코드가 없으므로 앱 테스트, 앱 빌드, 실제 AI 품질, 운영 배포는 확인 대상이 아닙니다.

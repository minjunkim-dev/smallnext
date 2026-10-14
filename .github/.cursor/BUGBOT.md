# Smallnext GitHub 자동화 리뷰 규칙

- Actions 기본 권한은 read다. 쓰기 권한·Secret은 필요한 job에만 둔다. 제품·dependency 빌드에는 배포 쓰기 권한과 production Secret을 주지 않는다.
- Secret을 쓰는 작업에서 PR 코드를 실행하지 않는다. `pull_request_target`은 신뢰하는 base만 checkout한다. 외부 Action은 전체 SHA로 고정한다. 입력은 env와 안전한 argv로 전달한다.
- 필수 하위 검사의 실패·취소·누락을 aggregate 성공으로 숨기지 않는다. 실제 GitHub required check 이름과 publisher, run·attempt·head·base·merge SHA의 신뢰 경계를 확인한다.
- 독립 집계·dependency·결정적 보안 검사를 보존한다. 봇의 승인·병합·자동 AI 리뷰 재활성화를 허용하지 않는다.
- Draft CD는 main에 포함된 전체 source SHA와 같은 SHA의 CI 성공을 확인한다. 읽기 빌드와 쓰기 게시를 분리한다. 새 미공개 Draft만 만들며 기존 Release·태그·asset을 덮어쓰지 않는다.
- YAML 설정과 PR 작성자의 개인 override, 대시보드·결제 상태, 실제 실행·댓글·artifact 근거를 구분한다. 설정 저장만으로 실행 성공을 보고하지 않는다.

기준 자료: `docs/CI.md`, `docs/adr/0001-trusted-ci-aggregation.md`, `docs/DRAFT_RELEASE.md`, `docs/REPOSITORY_SETUP.md`, `.ci/toolchains.json`.

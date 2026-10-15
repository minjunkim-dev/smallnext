# 미공개 API Draft CD

기존 배포 단위는 [API Dockerfile](../services/api/Dockerfile)의 Linux 컨테이너다.
[Private API draft](../.github/workflows/draft-release.yml)는 이 컨테이너를 파일로 저장한다.
registry push·production 배포·스토어 업로드·공개 Release 전환은 수행하지 않는다.
iOS·Android 출시 artifact는 앱 식별자·서명·스토어 계정이 필요하다. 이번 Draft의 지원 범위에 포함하지 않는다.

## 입력과 승인

버전은 `vMAJOR.MINOR.PATCH-alpha.N`이다. 전체 40자리 source SHA만 받는다.
source는 `main`에 포함되어야 한다. 정확히 같은 SHA의 기본 브랜치 CI를 확인한다.
Project checks의 모든 플랫폼 job과 Repository hygiene가 최신 attempt에서 성공해야 한다.
실패·취소·누락·skipped·이전 attempt의 복사 결과는 거부한다.
문서 변경으로 플랫폼 검사가 생략되었다면 같은 source에서 전체 Project checks를 수동 실행한다.
main push에서 iOS 시뮬레이터 테스트가 생략되었어도 같은 source에서 Project checks를 수동 실행한다. 수동 실행은 시뮬레이터 테스트를 항상 포함한다.
이미 있는 Draft·Release·태그·asset은 덮어쓰지 않는다.

1. 최종 PR의 전체 diff 독립 리뷰와 필수 CI를 완료한다.
2. 쓰기 권한 변경을 포함하는 최종 head SHA에 대해 사람의 승인을 받는다. [병합 조건](WORKFLOW.md#병합-조건)을 따른다.
3. 승인 후 squash로 병합한다. 승인한 source SHA의 main CI를 확인한다.
4. 충돌 없는 alpha 버전과 승인한 source SHA를 명시해 `main`에서 수동 실행한다.

검증용 artifact는 제품 코드가 동일한 기존 main SHA를 사용할 수 있다.
승인 요청에서 source SHA와 workflow 정책 head SHA를 구분한다. 이미 통과한 같은 source의 CI는 재사용한다.

```sh
gh workflow run draft-release.yml --repo minjunkim-dev/smallnext --ref main \
  -f version=v0.1.0-alpha.20261014 -f source-sha=FULL_MAIN_SOURCE_SHA
```

승인한 head가 바뀌면 다시 승인한다. 버전은 실행 직전에 충돌을 확인한다.
수동 실행 입력으로 공개 여부를 바꿀 수 없다. 생성은 항상 `draft=true`, `prerelease=true`다.

## 권한과 artifact

읽기 권한 build job이 선택 SHA를 checkout한다. production Secret을 전달하지 않는다.
기존 Dockerfile과 `make api-image-check`를 실행한다. 런타임 UID와 Compose 구성을 확인한다.
image에 실제 source SHA label을 넣는다. metadata에 checkout SHA·image ID·OS·CPU·Docker 버전·Dockerfile·Cargo.lock·Rust toolchain 해시·CI run/attempt를 기록한다.

새 쓰기 권한 draft job은 workflow 실행 SHA의 정책 코드만 checkout한다.
제품·dependency 코드·컨테이너를 실행하지 않는다. 이 실행의 artifact만 내려받는다.
파일 목록·checksum·버전·source metadata를 검증한다. 생성 직전에 CI·main 포함·버전·태그를 다시 확인한다.
업로드 뒤 Draft 상태·source·asset 목록·크기·GitHub digest가 있으면 digest·기존 Release 보존을 확인한다.

| asset | 내용 |
| --- | --- |
| `smallnext-api-image.tar.gz` | `docker image save`로 만든 API 이미지 |
| `metadata.json` | 버전·source·빌드 도구·dependency·CI 근거 |
| `SHA256SUMS` | 이미지와 metadata의 SHA-256 |

## 다운로드 검증

빈 디렉터리에 내려받는다. 기존 파일에 덮어쓰지 않는다.

```sh
gh release download VERSION --repo minjunkim-dev/smallnext --dir EMPTY_DIRECTORY
DRAFT_VERSION=VERSION SOURCE_SHA=FULL_MAIN_SOURCE_SHA \
  python3 scripts/draft_release.py verify --directory EMPTY_DIRECTORY
```

GitHub API asset digest와 로컬 SHA-256을 대조한다.
metadata의 source·version·image ID와 컨테이너 내부 source label을 확인한다.
가능한 환경에서 `gzip -dc IMAGE_FILE | docker image load`를 수행한다.
`docker run --rm --entrypoint id IMAGE_ID -u`가 `10001`인지 확인한다.
기존 이미지 태그가 충돌하면 load를 보류한다. DB·사용자 데이터에 접근하지 않는다.
이 smoke는 이미지 로딩·런타임 사용자만 확인한다. 실제 API/DB·AI·기기·운영 검증은 아니다.

## 신뢰 한계와 실패 처리

GitHub는 CI·main·태그·Release 생성 전체를 원자적으로 잠그지 않는다.
동일 workflow 실행은 직렬화하지만 외부 사람과 다른 workflow의 경합은 막지 못한다.
생성 후 경합 또는 업로드 실패를 발견하면 workflow를 실패 처리한다. 부분 Draft를 자동 삭제하지 않는다.
사람이 비공개 Draft와 오류를 확인한다. 재실행은 같은 버전을 덮어쓰지 않는다.
GitHub Actions artifact 다운로드의 digest 경고와 별개로 asset checksum도 검증한다.
Docker 기반 OS 패키지 저장소와 GitHub runner 도구는 완전한 재현 환경이 아니다.

검증 근거는 [셋업 보고서](PR_QUALITY_VALIDATION.md)에 기록한다.

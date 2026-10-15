# 사용자용 서버의 AI OFF 배포

[#158](https://github.com/minjunkim-dev/smallnext/issues/158)의 배포 runbook이다.
단일 Linux 서버에서 Docker Compose와 Caddy를 사용한다. DB는 외부 관리형 PostgreSQL이다.
서버 공급자와 DB 공급자는 사람이 선택한다. 레지스트리와 CI 자동 배포는 사용하지 않는다.

이 절차는 서버 AI를 켜지 않는다. `USER_SERVER_AI`는 설정하지 않는다.
제공사 API 키 생성·모델 확인·단가·예산 설정·AI 활성화·유료 호출은 [#47](https://github.com/minjunkim-dev/smallnext/issues/47)의 별도 승인 범위다.
실제 계정 준비는 [#162](https://github.com/minjunkim-dev/smallnext/issues/162), 실제 서버 실행은 [#164](https://github.com/minjunkim-dev/smallnext/issues/164)에서 사람이 수행한다.

## 1. 준비 wizard를 실행한다

값을 숨길 수 있는 로컬 대화형 터미널에서 실행한다. 파이프와 실행 로그 수집을 사용하지 않는다.

```sh
python3 scripts/prepare_production.py
```

wizard는 Linux·방화벽 80/443, DNS, 관리형 PostgreSQL, Firebase iOS 앱·Anonymous 인증, 서비스 계정 순서로 안내한다.
대시보드에서 계정과 자원을 만드는 작업은 사람이 수행한다. wizard는 서버를 배포하지 않는다.
관리형 DB의 자동 백업 보관 기간은 공급자 최소값으로 설정한다. 별도 백업을 추가하지 않는다.
서비스 계정에는 `firebaseauth.users.get`만 허용한다. 광범위한 Firebase 관리자 권한을 부여하지 않는다.

다음 두 파일을 권한 `0600`으로 저장한다. 두 파일은 Git에서 제외한다.

| 파일 | 용도 |
| --- | --- |
| `infra/production/.env.production` | 서버의 Compose 환경 파일 |
| `apps/ios/Config/Local.xcconfig` | 로컬 iOS 공개 client 설정 |

예시는 [서버 환경 파일](../infra/production/.env.production.example)과 [iOS 설정](../apps/ios/Config/Local.xcconfig.example)에 있다.
서버 환경 파일은 `docker compose --env-file`로만 읽는다. 셸에서 `source`하지 않는다.
이미 확인한 본인 익명 UID가 없으면 허용 목록을 비워 둔다. 서버 AI OFF 준비에는 UID가 필요하지 않다.
UID·키·토큰·환경 파일 내용을 채팅·Issue·로그에 붙이지 않는다.
#162에는 공급자 이름·지역·백업 보관 기간·서비스 계정 권한만 기록한다.

## 2. 서버의 비밀 파일을 배치한다

서버에 Python 3.9 이상, Docker Engine, Docker Compose 2.24.4 이상과 systemd를 준비한다.
운영 계정은 Docker 실행 권한과 `/opt/smallnext`의 배포 파일을 쓸 권한이 필요하다.
SSH 접근과 파일 전송 권한은 로컬 운영 계정에서만 사용한다. CI에 넣지 않는다.
서버의 5432 포트를 공개하지 않는다. 관리형 DB의 TLS 접속 조건과 접근 제한을 확인한다.
최초 배포 전에 서버에서 `docker pull caddy:2-alpine`로 기존 프록시 이미지를 준비한다.

1. 서버에 `/opt/smallnext/infra/production`을 만든다.
2. 보호한 파일 전송 경로로 `.env.production`을 같은 서버 경로에 배치한다. 운영 계정 소유와 권한 `0600`을 유지한다.
3. 서비스 계정 JSON을 wizard에서 지정한 서버의 절대 디렉터리에 `service-account.json` 이름으로 배치한다.
4. credential 디렉터리에는 해당 JSON만 둔다. 컨테이너 사용자 UID `10001`이 읽을 수 있게 소유권을 지정한다. 디렉터리 권한은 `0500`, 파일 권한은 `0400`으로 제한한다.
5. DNS A/AAAA가 이 서버를 가리키는지 확인한다. Caddy가 80/443으로 인증서를 발급할 수 있게 한다.

서버 환경 파일의 `FIREBASE_CREDENTIALS_DIR`은 **서버**의 경로다. 개발 Mac의 경로를 넣지 않는다.
Compose는 이 디렉터리를 `/run/secrets/firebase`에 읽기 전용으로 연결한다.
이미지에는 서비스 계정 JSON을 넣지 않는다. `docker compose config`의 전체 출력에는 비밀 값이 포함될 수 있으므로 출력·게시하지 않는다.

## 3. 승인한 이미지 묶음을 준비한다

운영 구성과 이미지 변경은 `one-way/broad`다. 사람이 통합 PR의 최종 head와 영향 범위를 승인한다.
승인한 변경을 병합한 뒤 정확한 source SHA의 main CI를 확인한다.
[미공개 Draft CD](DRAFT_RELEASE.md)의 절차로 해당 source의 이미지 묶음을 만든다.
이 runbook은 새 Draft 생성 권한이나 실행 승인을 대신하지 않는다.

빈 로컬 디렉터리에 승인한 Draft의 세 asset만 내려받는다.

```sh
gh release download VERSION --repo minjunkim-dev/smallnext --dir EMPTY_DIRECTORY
DRAFT_VERSION=VERSION SOURCE_SHA=FULL_MAIN_SOURCE_SHA \
  python3 scripts/draft_release.py verify --directory EMPTY_DIRECTORY
```

`smallnext-api-image.tar.gz`, `metadata.json`, `SHA256SUMS`를 함께 보관한다.
Draft 버전·source SHA·GitHub asset digest·로컬 checksum의 대조 기준은 [Draft 다운로드 검증](DRAFT_RELEASE.md#다운로드-검증)을 따른다.
현재 월 삭제 바이너리를 포함한 승인 이미지인지 확인한다. 이전 이미지에는 바이너리가 없을 수 있다.
서버에서 이미지를 다시 빌드하지 않는다.

## 4. 이미지를 전송하고 배포한다

다음 명령의 대문자 항목을 승인한 값과 로컬 경로로 바꾼다. 비밀 값을 명령 인자에 넣지 않는다.

```sh
python3 scripts/deploy_production.py \
  --target ssh --ssh-host DEPLOY_USER@SERVER_HOST \
  --bundle /ABSOLUTE/EMPTY_DIRECTORY \
  --version VERSION --source-sha FULL_MAIN_SOURCE_SHA \
  --deploy-dir /opt/smallnext \
  --env-file /opt/smallnext/infra/production/.env.production \
  --url https://API_DOMAIN
```

스크립트는 검증한 이미지 묶음과 필요한 Compose 파일을 전송한다.
서버의 기존 환경 파일과 credential JSON은 전송하거나 출력하지 않는다.
묶음의 checksum·metadata와 적재한 이미지의 ID·source label을 대조한다.
Compose는 지정 이미지를 `--no-build --pull never`로 실행한다.
배포한 이미지 ID는 비밀 값 없는 `infra/production/.env.image`에 저장한다. 월 삭제도 이 이미지 ID를 사용한다.
스크립트가 서버 AI OFF 준비 범위를 벗어난 환경 설정을 거부하면 #47의 기존 활성화 계획을 확인한다. 이 절차에서 설정을 켜지 않는다.

이전 Draft의 `smallnext-api:ci` 태그가 다른 이미지 ID를 가리키면 적재를 보류한다.
이 경우 현재 이미지 ID·`.env.image`·직전 묶음을 먼저 보존한다.
서버에서 충돌 태그를 별도의 보관 태그로 옮긴 뒤 충돌 태그만 해제한다. 이미지 ID나 보관 태그는 삭제하지 않는다.

```sh
docker image inspect smallnext-api:ci --format '{{.Id}}'
docker image tag smallnext-api:ci smallnext-api:retained-PREVIOUS_DIGEST_SUFFIX
docker image rm smallnext-api:ci
```

`PREVIOUS_DIGEST_SUFFIX`는 앞에서 확인한 기존 이미지 digest로 바꾼다. 보관 태그가 충돌하면 다른 새 이름을 사용한다.
`--force`를 사용하지 않는다. 보관을 확인한 뒤 같은 배포 명령을 다시 실행한다.

기동 뒤 `/health` 200, `/ready` 200, `POST /v1/suggestions` 404를 확인한다.
성공 출력에는 응답 코드만 남긴다. HTTP 본문·인증 토큰·환경 값은 출력하지 않는다.
실패하면 서버의 상태를 확인한다. 스크립트는 운영 DB나 데이터를 자동으로 되돌리지 않는다.

## 5. 월 삭제 일정을 등록한다

호스트의 `/etc/systemd/system/`에 다음 두 [일정 정의](../infra/production/systemd)를 배치한다.
작업 경로는 `/opt/smallnext`다. 다른 경로로 배포했다면 unit의 `WorkingDirectory`를 먼저 맞춘다.

```sh
sudo install -m 0644 infra/production/systemd/smallnext-purge-ai-budget.service /etc/systemd/system/
sudo install -m 0644 infra/production/systemd/smallnext-purge-ai-budget.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smallnext-purge-ai-budget.timer
sudo systemctl start smallnext-purge-ai-budget.service
sudo systemctl status smallnext-purge-ai-budget.timer --no-pager
sudo journalctl -u smallnext-purge-ai-budget.service --no-pager -n 20
```

정의 파일은 승인한 저장소 checkout에서 가져온다. 실제 등록과 수동 실행 결과는 사람이 #164에 기록한다.
timer는 매월 1일 `00:01 UTC`에 실행한다. `Persistent=true`가 중단 중 놓친 실행을 다음 활성화 때 처리한다.
서비스는 기존 Compose `api`를 일회 실행한다. API 프로세스가 정지해 있어도 DB에 연결해 지난 UTC 월의 합계만 삭제한다.
성공·실패는 호스트 journal의 고정 문구로 확인한다. 인증·제공사 호출은 없다.
API의 시작·매분 삭제도 유지한다. 일정 등록만으로 실제 삭제 성공을 판정하지 않는다.

## 6. 확인 결과와 미확인 범위를 기록한다

#164에 확인 UTC 시각·배포 이미지 태그 또는 ID·source SHA·200/200/404 결과·timer 실행 결과만 기록한다.
실제 도메인의 공인 TLS 인증서 유효성도 확인한다. 로컬 HTTP smoke로 공인 TLS를 확인했다고 보고하지 않는다.

iOS 설정과 빌드 명령은 [iOS 연결](SERVER_AI.md#ios-연결)과 [개발 환경](DEVELOPMENT.md#ios)을 따른다.
#164의 Release 익명 로그인 조건은 [기존 OFF 경로에 대한 질문](https://github.com/minjunkim-dev/smallnext/issues/164#issuecomment-6190868774)을 먼저 확정한다.
이 질문을 해결하려고 기능 플래그를 임의로 켜지 않는다.
유료 API·사람 검토·실기기·공개 승인은 각각 별도 확인 범위다.

## 7. 직전 이미지로 되돌린다

배포 전에 직전 검증 이미지의 세 asset, 버전과 source SHA를 별도 경로에 보존한다.
같은 배포 명령에 직전 묶음의 `--bundle`, `--version`, `--source-sha`를 넣어 다시 실행한다.
새 이미지로 다시 빌드하지 않는다. 되돌린 뒤 200/200/404와 `.env.image`의 이미지 ID를 다시 확인한다.
월 삭제 timer도 되돌린 이미지에서 `purge-ai-budget`을 실행할 수 있어야 한다.

이미지 롤백은 DB 마이그레이션을 되돌리지 않는다. 이전 이미지와 현재 DB의 호환성을 먼저 확인한다.
호환성이 확인되지 않으면 배포를 보류한다. 운영 DB를 삭제하거나 과거 백업으로 자동 복원하지 않는다.

## 로컬 검증 범위

```sh
make api-image-build
make api-image-check
```

검사는 고정 테스트 PostgreSQL과 운영 Caddy→API를 로컬에서 실행한다.
월 삭제는 테스트용 격리 schema를 사용한다. 배포 검사는 로컬에서 만든 합성 Draft 형식 묶음을 사용한다.
실제 배포 스크립트로 묶음 복사·적재·Compose 기동·상태 확인을 실행한다.
합성 묶음의 성공은 GitHub CI 원본의 provenance나 실제 서버의 SSH·TLS를 증명하지 않는다.

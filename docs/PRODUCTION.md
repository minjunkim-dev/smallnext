# 사용자용 서버의 AI OFF 배포

[#158](https://github.com/minjunkim-dev/smallnext/issues/158)의 배포 runbook이다.
단일 Linux 서버에서 Docker Compose와 Caddy를 사용한다. DB·익명 인증은 Supabase Free로 통합한다.
서버는 Supabase DB에 PostgreSQL로 직접 연결한다. Data API는 OFF, 자동 RLS는 ON으로 유지한다.
서버 공급자는 사람이 선택한다. 레지스트리와 CI 자동 배포는 사용하지 않는다.

이 절차는 서버 AI를 켜지 않는다. `USER_SERVER_AI`는 설정하지 않는다.
제공사 API 키 생성·모델 확인·단가·예산 설정·AI 활성화·유료 호출은 [#47](https://github.com/minjunkim-dev/smallnext/issues/47)의 별도 승인 범위다.
Supabase 프로젝트 생성·연결은 [#168](https://github.com/minjunkim-dev/smallnext/issues/168)에서 별도로 확인했다.
[#162](https://github.com/minjunkim-dev/smallnext/issues/162)의 전체 wizard 실행과 [#164](https://github.com/minjunkim-dev/smallnext/issues/164)의 실제 서버 실행은 보류한다.
아래 절차는 해당 실행을 승인한 뒤에 따른다. 로컬 연결의 확인 범위는 [서버 AI](SERVER_AI.md#supabase-free-연결-확인과-남은-조건)를 따른다.

## 1. 준비 wizard를 실행한다

값을 숨길 수 있는 로컬 대화형 터미널에서 실행한다. 파이프와 실행 로그 수집을 사용하지 않는다.

```sh
python3 scripts/prepare_production.py
```

wizard는 Linux·방화벽 80/443, DNS, Supabase PostgreSQL·백업 조건, Anonymous 인증, DB 권한 순서로 안내한다.
wizard는 서버를 배포하거나 계정을 생성하지 않는다.
Supabase Free에는 자동 백업이 없다. 이전의 공급자 최소 자동 백업 조건을 충족했다고 처리하지 않는다.
[#170](https://github.com/minjunkim-dev/smallnext/issues/170)에서 예산 데이터만 12시간마다 암호화해 최대 7일 보관하는 조건을 확정했다.
RPO·RTO 목표는 각각 24시간이다. 목표의 확정은 실제 달성 검증과 다르다.
익명 계정과 세션은 백업하지 않는다. 계정을 유실하면 재생성하고 허용 UID를 다시 등록한다.
목표·진행 상태는 기기에 유지한다. Mac의 Git 밖 폴더에서 최초 검증을 수행한다.
실제 서버의 자동 백업 등록은 #164까지 보류한다. [공급자 백업 조건](https://supabase.com/docs/guides/platform/backups)을 확인한다.

다음 파일을 권한 `0600`으로 저장한다. 실제 파일은 Git에서 제외한다.

| 파일 | 용도 |
| --- | --- |
| `infra/production/.env.production` | `smallnext_api` capability를 가진 runtime LOGIN 연결 |
| `infra/production/.env.migration` | schema owner 연결. migrate 서비스에만 제공 |
| `infra/production/.env.backup` | `smallnext_backup` capability를 가진 읽기 전용 LOGIN 연결 |
| `apps/ios/Config/Local.Release.xcconfig` | 운영용 iOS 공개 client 설정 |

예시는 [서버 환경 파일](../infra/production/.env.production.example)과 [iOS 설정](../apps/ios/Config/Local.xcconfig.example)에 있다.
서버 환경 파일은 `docker compose --env-file`로만 읽는다. 셸에서 `source`하지 않는다.
이미 확인한 본인 익명 UID가 없으면 허용 목록을 비워 둔다. 서버 AI OFF 준비에는 UID가 필요하지 않다.
UID·키·토큰·환경 파일 내용을 채팅·Issue·로그에 붙이지 않는다.
#162에는 공급자 이름·지역·확정한 백업 조건·DB 권한과 미확인 범위만 기록한다.

## 2. 서버의 비밀 파일을 배치한다

서버에 Python 3.9 이상, Docker Engine, Docker Compose 2.24.4 이상과 systemd를 준비한다.
운영 계정은 Docker 실행 권한과 `/opt/smallnext`의 배포 파일을 쓸 권한이 필요하다.
SSH 접근과 파일 전송 권한은 로컬 운영 계정에서만 사용한다. CI에 넣지 않는다.
서버의 5432 포트를 공개하지 않는다. 관리형 DB의 TLS 접속 조건과 접근 제한을 확인한다.
최초 배포 전에 서버에서 `docker pull caddy:2-alpine`로 기존 프록시 이미지를 준비한다.

1. 서버에 `/opt/smallnext/infra/production`을 만든다.
2. 보호한 파일 전송 경로로 세 환경 파일을 같은 서버 경로에 배치한다. 운영 계정 소유와 권한 `0600`을 유지한다.
3. 공식 CA를 `tls/supabase-ca.crt`로 배치한다. DB URL에 `sslmode=verify-full&sslrootcert=/etc/smallnext/tls/supabase-ca.crt`를 지정한다. 서버 비밀번호를 앱에 넣지 않는다.
4. 운영용 LOGIN 역할·마이그레이션 권한·실행 권한을 #164 전에 사람이 검토한다. 관리용 DB 연결의 성공은 이 승인을 대신하지 않는다.
5. DNS A/AAAA가 이 서버를 가리키는지 확인한다. Caddy가 80/443으로 인증서를 발급할 수 있게 한다.

마이그레이션 0004는 앱 테이블의 RLS를 켜고 client 역할의 테이블 접근과 인증 함수 실행을 차단한다.
마이그레이션 0005는 `smallnext_api`와 `smallnext_backup` NOLOGIN capability를 만든다.
runtime은 예산 CRUD와 `smallnext_session_active` 실행만 허용한다. backup은 예산의 명시한 네 열만 읽는다.
별도 LOGIN에는 해당 capability만 부여한다. owner·BYPASSRLS·앱 schema CREATE 권한을 부여하지 않는다.
API는 `API_AUTO_MIGRATE=0`으로 실행한다. 배포 스크립트가 별도 migrate 서비스로 먼저 마이그레이션한다.
Firebase 서비스 계정과 credential JSON mount는 사용하지 않는다.
`docker compose config`의 전체 출력에는 비밀 값이 포함될 수 있으므로 출력·게시하지 않는다.

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
  --migration-env-file /opt/smallnext/infra/production/.env.migration \
  --url https://API_DOMAIN
```

스크립트는 검증한 이미지 묶음과 필요한 Compose 파일을 전송한다.
서버의 기존 환경 파일은 전송하거나 출력하지 않는다.
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

## 운영 지표를 조회한다

AI ON 운영 중에 `[FROM, TO)` UTC 날짜 범위의 익명 지표를 JSON으로 출력한다.

```sh
docker compose --env-file infra/production/.env.production --env-file infra/production/.env.image \
  -f infra/production/compose.yaml run --rm --no-deps --pull never -T \
  api report-ai-metrics 2026-11-01 2026-11-15
```

출력은 요청 수·결과별 수·서버 처리 ms의 p50/p95/p99·정산 비용·고유 사용자 수·한도 차단 수·일별 사용자 수다.
`started` 결과는 취소된 요청이거나 조회 시점에 진행 중인 요청이다. 사용자 수는 30일 보관 범위 안에서만 정확하다.
비용은 설정 단가로 계산한 값이다. Anthropic 청구액과 대조하기 전에는 실제 비용으로 보고하지 않는다.
지표를 기록할 때 기간·배포 이미지 source SHA·서버 지역·모델/effort·표본 수를 함께 남긴다.
인증 실패·예산 차단·동시 요청·처리 용량 초과는 API 컨테이너 로그의 `AI request rejected: <사유>` 고정 문구로 센다. 로그에는 UID·토큰·본문이 없다.

## 6. 확인 결과와 미확인 범위를 기록한다

#164에 확인 UTC 시각·배포 이미지 태그 또는 ID·source SHA·200/200/404 결과·timer 실행 결과만 기록한다.
실제 도메인의 공인 TLS 인증서 유효성도 확인한다. 로컬 HTTP smoke로 공인 TLS를 확인했다고 보고하지 않는다.

iOS 설정과 빌드 명령은 [iOS 연결](SERVER_AI.md#ios-연결)과 [개발 환경](DEVELOPMENT.md#ios)을 따른다.
#164의 Release 익명 로그인은 아래 인증 전용 테스트를 사용한다. [확정 범위](https://github.com/minjunkim-dev/smallnext/issues/164#issuecomment-6286553318)와 [준비 티켓 #191](https://github.com/minjunkim-dev/smallnext/issues/191)을 따른다.
유료 API·사람 검토·실기기·공개 승인은 각각 별도 확인 범위다.

### Release AI OFF 인증 전용 검증

이 절차는 실제 실행 승인을 받은 뒤 사람이 수행한다. 준비 구현·기본 skip은 실제 인증 성공의 근거가 아니다.
제품의 `user_server_ai`·`ios_core_flow`는 OFF로 유지한다. 테스트는 제품 AI 공급자가 비활성 상태인지 확인한다.
기존 `SupabaseAnonymousIdentity`를 직접 사용한다. 제품의 Keychain session과 분리한 고유 service·key를 만들고 자기 key만 제거한다.
검증 transport는 Release 번들의 프로젝트로 보내는 `POST /auth/v1/signup` 한 번만 허용한다. redirect·재시도·AI 요청을 거부한다.
CAPTCHA 설정이 있으면 기존 앱 sheet에서 사람이 완료한다. 부분 설정은 실패한다. CAPTCHA를 임의로 끄지 않는다.
실제 CAPTCHA 검증에는 [#193](https://github.com/minjunkim-dev/smallnext/issues/193)의 callback 서명 수정과 selector 회귀가 포함된 빌드를 사용한다.
이 회귀는 navigation callback 등록만 확인한다. 실제 CAPTCHA 성공은 위 절차에서 따로 확인한다.

1. Release 공개 client 설정·대상 Supabase 프로젝트·익명 인증 허용 상태를 확인한다. [iOS 연결](SERVER_AI.md#ios-연결)의 설정을 사용한다. 토큰·UID·key·설정 원문을 결과에 복사하지 않는다.
2. 기존 검사와 충돌하지 않는 본인 소유 simulator를 선택한다. 아래 `SIMULATOR_UDID`를 해당 UUID로 바꾼다. 저장소 기준 Xcode를 선택한다.
3. 아래 명령을 실행한다. 익명 계정이 서버에 한 개 생길 수 있다. Keychain 정리는 서버의 익명 계정을 삭제하지 않는다. 실패했을 때 자동 재실행하지 말고 프로젝트 상태를 먼저 확인한다.

```sh
TEST_RUNNER_SMALLNEXT_LIVE_AUTH_CHECK=1 \
python3 ~/.agents/tools/agent_workflow.py check -- \
xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme Smallnext \
  -configuration Release ENABLE_TESTABILITY=YES \
  -destination 'platform=iOS Simulator,id=SIMULATOR_UDID' \
  -onlyUsePackageVersionsFromResolvedFile -skipPackageUpdates \
  -only-testing:SmallnextTests/ReleaseAuthValidationTests/testOptInReleaseAnonymousAuthentication \
  -test-timeouts-enabled YES -maximum-test-execution-time-allowance 180 \
  CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- CODE_SIGNING_REQUIRED=NO test
```

[`TEST_RUNNER_`](https://developer.apple.com/documentation/xcode/environment-variable-reference)는 Xcode가 접두사를 제거한 뒤 테스트 프로세스로 전달한다.
[`ENABLE_TESTABILITY=YES`](https://developer.apple.com/documentation/xcode/build-settings-reference)는 Release의 `@testable import`를 허용하는 해당 명령의 설정이다.
명시적 opt-in이 없으면 신원·Keychain·네트워크 생성 전에 skip한다. Debug에서 opt-in하면 실패한다.
일반 로컬 검사·CI에는 opt-in을 설정하지 않는다. 이 경로는 앱 사용자에게 로그인 버튼을 추가하지 않는다.
테스트에는 실제 토큰·UID·key·HTTP 본문·공급자 오류 원문을 출력하는 진단 코드를 추가하지 않는다.

4. 성공하면 #164에 source SHA·Xcode 버전·Release·두 플래그 OFF·익명 인증 성공·Auth 요청 1회·로컬 session 정리 결과만 기록한다. 테스트 로그·xcresult 원문을 공개 첨부하지 않는다.
5. 실패·취소·timeout이면 성공으로 표시하지 않는다. 자기 session 정리 실패가 있으면 테스트가 기록한 고정 오류를 남긴다. 프로세스가 강제 종료되면 정리를 보장할 수 없으므로 해당 simulator를 본인 검증 절차로 정리한다.

이 검증은 Supabase 인증만 확인한다. 실제 서버 배포·TLS·200/200/404·timer·AI 호출·실기기 완료는 각각 별도 근거가 필요하다.

## 예산 백업과 복원 검사

개발은 로컬 PostgreSQL과 인증 fixture를 사용한다. 기존 Supabase 프로젝트는 운영 준비용이다.
개발·CI의 `TEST_DATABASE_URL`에 운영 연결을 지정하지 않는다.
백업은 운영 DB와 분리한 Git 밖 `0700` 폴더에 보관한다. 생성 파일과 설정은 `0600`으로 제한한다.
`age` 공개 recipient만 백업 호스트에 배치한다. 복호화 identity는 별도 경로의 복구 기기에 둔다.
identity의 별도 안전한 복사본 보관은 사람이 완료한다.

```sh
python3 scripts/backup_ai_budget.py snapshot \
  --directory /PRIVATE/BACKUP_DIRECTORY --recipients-file /PRIVATE/RECIPIENTS_FILE
python3 scripts/backup_ai_budget.py check-restore /PRIVATE/BACKUP_DIRECTORY/SNAPSHOT.age \
  --identity-file /SEPARATE/IDENTITY_FILE
python3 scripts/backup_ai_budget.py expire --directory /PRIVATE/BACKUP_DIRECTORY
```

`snapshot`은 읽기 전용 `BACKUP_DATABASE_URL` 환경변수를 사용한다.
공식 CA 파일의 호스트 경로는 `BACKUP_SSL_ROOT_CERT_FILE`로 지정한다. 컨테이너에 읽기 전용으로 연결한다.
셸의 입력 기록에 비밀 값을 넣지 않는다. 보호한 파일에서 환경변수로 읽는다.
예시는 [백업 설정](../infra/production/.env.backup.example)을 따른다.
`check-restore`는 명시한 로컬 `TEST_DATABASE_URL`의 새 격리 schema만 사용한다.
운영 복원 명령은 제공하지 않는다. 복구 시 현재 UTC 월을 항상 차단하고 기존 비용을 낮추지 않는다.
복원 검사 성공은 AI 재개 승인이나 최신 실제 비용 확인을 대신하지 않는다.
파일명과 암호문 내부의 최초 생성 시각을 검증한다. 복사나 mtime 변경으로 7일 기한을 연장하지 않는다.

timer 정의는 00:00/12:00 UTC에 백업한다. `age`·Docker·보호한 설정·승인한 실패 알림 handler가 필요하다.
실제 서버의 `/etc/smallnext/backup.env`와 외부 백업 경로를 준비한다.
`smallnext-backup-alert.service`가 실패를 전달하는지 검증하기 전에는 timer를 활성화하지 않는다.
실제 timer 설치·자동 만료·실패 알림·정기 복원·RPO/RTO 달성 검증은 #164에서 수행한다.

## CAPTCHA와 접근 제한의 배포 전 조건

Caddy는 `/auth/captcha/`에서 정적 Turnstile 페이지를 제공한다.
iOS에는 HTTPS 원점인 `SMALLNEXT_AUTH_CAPTCHA_URL`과 공개 `SMALLNEXT_TURNSTILE_SITE_KEY`를 함께 지정한다.
앱은 정확한 원점·main frame·nonce를 검증하고 신규 익명 가입에만 CAPTCHA 토큰을 전달한다.
기존 세션 갱신은 CAPTCHA를 요구하지 않는다. 토큰·페이지 query·UID를 로그에 남기지 않는다.
도메인이 없으므로 실제 widget 생성과 Supabase CAPTCHA 활성화는 보류한다.
도메인 준비 후 실제 iOS 가입·취소·실패를 검증하고 활성화한다.
운영 서버의 고정 egress IP와 승인한 관리 접속 경로가 정해지면 #164 전에 DB IP 제한을 적용한다.
익명 가입 제한은 IP당 시간당 30회다. 부하 근거 없이 연결 수와 제한 값을 조정하지 않는다.
관리자 MFA는 앱 사용자의 MFA와 별도다. 관리자 인증 앱을 등록하고 접근 수단을 안전하게 보관한다.

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

# 개발 환경과 실행

환경 재현성 기준: 2026-10-05 KST.

## 구성

| 대상 | 구성 |
| --- | --- |
| iOS | SwiftUI, GRDB 7.11.1, URLSession |
| Android | Compose, Room 2.8.5, Retrofit 3.0.0, OkHttp 4.12.0 |
| API | Rust 1.98.0, Axum, Tokio, Serde, SQLx, utoipa, tracing |
| 개발 DB | PostgreSQL 18, Docker Compose |
| 운영 템플릿 | Caddy, API 컨테이너, 외부 관리형 PostgreSQL |

첫 기능 검증 플랫폼은 iOS입니다.
Android는 기본 실행과 저장 검증을 함께 수행합니다.
현재 두 앱에는 시작 화면과 DB 초기화만 있습니다.
앱의 목표·행동 기능, AI 연결, 실제 Firebase 인증, 동기화는 다음 작업 범위입니다.
현재 API에는 사용자 데이터를 다루는 경로가 없습니다.

## 필요한 도구

- iOS: Xcode 27.0 (27A266a), simulator SDK 27.0, iOS runtime 27.0.
- Android: Temurin JDK (설치 선택값 17.0.20+1, 실제 runtime 17.0.20.1+1), Android SDK 37, Build Tools 36.0.0, 에뮬레이터.
- API: rustup, Rust 1.98.0, Docker Compose v2, Python 3, make.

Rust 기준은 `rust-toolchain.toml`입니다. 다른 도구의 기준은 `.ci/toolchains.json`입니다.
`make api-setup`은 고정 Rust와 rustfmt·clippy를 설치합니다.
검사 명령은 다른 Rust·JDK·Xcode 버전을 차단합니다.
개발 PC와 CI는 같은 Make 명령을 사용합니다.
개인 PC의 기존 DB, 캐시와 환경 파일은 CI에 전달하지 않습니다.

iOS 지원 하한은 우선 17.0, Android 지원 하한은 API 26입니다.
이 값은 초기 빌드 기준입니다. 출시 지원 범위는 별도로 확인합니다.
기본 앱 식별자는 `dev.smallnext.app`입니다.
서명 팀, 스토어 등록, 실제 기기 설치는 설정하지 않았습니다.

## 개발 DB와 API

저장소 루트에서 실행합니다.

```sh
cp .env.example .env
make dev-db
make api
```

DB는 `127.0.0.1:55432`, API는 `127.0.0.1:8080`을 사용합니다.
예제 비밀번호는 로컬 개발 전용입니다.
이미 같은 포트를 사용하면 `.env`에서 포트와 URL을 함께 변경합니다.

| 경로 | 의미 |
| --- | --- |
| `GET /health` | API 프로세스 응답 확인 |
| `GET /ready` | PostgreSQL 연결 확인; 실패하면 503 |
| `GET /openapi.json` | 실행 중인 API의 명세 |

서버를 시작할 때 PostgreSQL 마이그레이션을 적용합니다.
공유 환경에서는 배포 전 마이그레이션 절차를 별도로 검토합니다.
개발 DB를 멈출 때는 `make dev-db-stop`을 사용합니다.
이 명령은 저장 볼륨을 삭제하지 않습니다.

## 개발 전용 AI

[개발 모델 결정](https://github.com/minjunkim-dev/smallnext/issues/17#issuecomment-5993865166)과
[개발 중 구독 연결 결정](https://github.com/minjunkim-dev/smallnext/issues/17#issuecomment-5994138248)을 따릅니다.
공식 Codex CLI가 기존 ChatGPT OAuth 로그인을 사용합니다. 새 API 키를 만들지 않습니다.
인증정보는 Codex가 관리합니다. 실행기는 토큰을 읽거나 추출하지 않습니다.
Codex CLI 0.160.0과 Python 3로 검증합니다. Python 3는 모의 CLI 회귀 테스트에만 사용합니다.
개발 연결은 skill 목록의 문맥 한도를 1토큰으로 제한합니다.
CLI가 모든 skill 설명을 제거했다는 정확한 안내만 허용합니다. 다른 오류 항목은 답을 차단합니다.
CLI 변경 후에는 연결과 도구 차단을 다시 확인합니다.

저장소 루트에서 실행합니다.

```sh
codex login status
# 기본 OFF: 모델을 호출하지 않습니다.
cargo run --locked --manifest-path services/api/Cargo.toml --bin development-ai \
  < services/api/examples/development-ai-input.json
# 이 실행만 ON: 생성 1회와 별도 의미 검사 1회를 수행합니다.
cargo run --locked --manifest-path services/api/Cargo.toml --bin development-ai -- \
  --enable-local-ai < services/api/examples/development-ai-input.json
```

로그인이 없으면 `codex login`에서 ChatGPT 로그인을 선택합니다.
키와 목표 자료를 채팅, PR, 운영 로그에 붙여 넣지 않습니다.
예제 입력은 합성한 책상 정리 목표입니다. 특정 목표 분야로 기능을 제한하지 않습니다.

`disposition: accepted`와 `applied: true`인 답만 현재 행동으로 적용합니다.
거부, 불확실, 오류, 시간 초과에서는 기존 행동을 유지합니다. 자동 재생성은 없습니다.
결과 JSON은 개발 검토 자료입니다. 실행기의 종료 코드만으로 수용 여부를 판단하지 않습니다.
요청 모델은 결과에 표시합니다. CLI가 실제 모델 ID를 반환하지 않으므로 실제 모델 확인을 주장하지 않습니다.

입력 구조는 예제와 Rust의 `AiInput`이 기준입니다.
`previous_proposals`는 실행하지 않은 제안 이력입니다. 마지막 제안을 기존 행동으로 사용합니다.
완료한 행동의 ID와 남은 작업은 코드가 원본과 비교합니다. 모델은 완료 상태를 변경할 수 없습니다.
의미 검사기는 원본 입력과 후보를 새 호출에서 함께 검사합니다.
다섯 기준을 모두 수용한 답만 적용합니다. 이 판정도 출시 품질의 증거는 아닙니다.
개발 프롬프트와 입력 구조는 이전 수동 비교 자료와 다릅니다. 출시 전에 별도로 검증합니다.

`ActionState`는 실행 중 중복 요청을 막습니다. 입력 변경·사용자 취소 시 `cancel()`을 호출합니다.
취소 후 도착한 답과 다른 상태의 답은 적용하지 않습니다.
취소·시간 초과는 로컬 CLI 프로세스를 종료합니다. 원격 처리와 구독 사용량의 취소는 보장하지 않습니다.
개발 한도는 원본·생성 입력 32 KiB, 검사 입력 192 KiB, CLI 출력 128 KiB, 두 단계 합계 120초입니다.
검사 입력 한도는 원본과 생성 결과를 함께 전달할 공간을 포함합니다.
이는 임시 보호 한도입니다. 출시 비용·지연·출력 토큰 한도가 아닙니다.
임시 폴더에는 고정 프롬프트와 스키마만 기록합니다. 완료·실패 시 폴더를 제거합니다.

플래그 기본값은 [등록 파일](../config/feature-flags.json)에서 읽습니다.
ON은 위 로컬 실행 옵션으로만 허용합니다. HTTP 서버와 모바일 앱에는 AI 경로를 추가하지 않았습니다.
운영 API 연결과 자격증명은 개발 완료 후 별도로 준비합니다.

## iOS

`apps/ios/Smallnext.xcodeproj`를 Xcode에서 엽니다.
`Smallnext` scheme과 iPhone 시뮬레이터를 선택한 뒤 실행합니다.
서명 팀 없이 시뮬레이터에서 실행할 수 있습니다.
GRDB 버전과 Git 커밋은 `Package.resolved`에 고정했습니다.

CLI 검사에서는 설치한 시뮬레이터 이름을 지정합니다.

```sh
make ios-check IOS_SIMULATOR='iPhone 18 Pro'
```

커밋한 Xcode 프로젝트를 바로 사용할 수 있습니다.
검사는 iOS 27.0 runtime에 있는 iPhone만 선택합니다.
`IOS_SIMULATOR`를 생략하면 해당 runtime의 기기를 자동 선택합니다.
다른 runtime의 부팅한 기기는 대신 사용하지 않습니다.
고정 Xcode가 `/Applications/Xcode_27.0.app`에 있으면 검사에서 자동 선택합니다.
다른 경로이면 `DEVELOPER_DIR`을 해당 Xcode의 `Contents/Developer` 경로로 지정합니다.
전역 `xcode-select` 설정은 변경하지 않습니다.
CI는 [GitHub의 `xcode-27` 실행 환경](https://github.blog/changelog/2026-07-16-xcode-27-runner-image-now-in-public-preview/)을 사용합니다. 이 실행 환경은 현재 public preview입니다.
구조를 다시 생성할 때만 XcodeGen 2.46.0을 사용합니다.

```sh
xcodegen generate --spec apps/ios/project.yml
```

`project.yml`의 구조를 변경하면 생성한 프로젝트도 함께 갱신합니다.
앱 화면은 사용자 안내만 표시합니다.
DB는 Application Support에 저장하며 시작 시 마이그레이션을 적용합니다.

## Android

`apps/android/`를 Android Studio에서 엽니다.
Gradle Wrapper, 버전 목록, Room 내보내기 스키마를 커밋했습니다.
SDK 경로는 로컬 설정 또는 `ANDROID_HOME`으로 지정합니다.

```sh
export JAVA_HOME=/path/to/pinned-temurin-jdk
export ANDROID_HOME=/path/to/android-sdk
make android-sdk
make android-check
make android-device-check
```

마지막 명령에는 부팅한 에뮬레이터나 연결한 기기가 필요합니다.
먼저 Android command-line tools를 `$ANDROID_HOME/cmdline-tools/latest`에 설치하고 SDK 라이선스를 승인합니다.
`make android-sdk`는 고정 compile SDK와 Build Tools를 설치합니다.
API 37의 SDK Manager 패키지 이름은 `platforms;android-37.0`입니다. Gradle의 `compileSdk = 37`과 구분합니다.
CI 기기 테스트는 `.ci/toolchains.json`의 Android 35 google_apis x86_64 이미지를 사용합니다.
로컬 기기의 OS·CPU가 다르면 같은 명령으로 수행한 추가 플랫폼 검사로 기록합니다.
Room 테스트는 별도 테스트 DB 파일을 생성하고 삭제합니다.
앱의 실제 DB 파일을 삭제하지 않습니다.
에뮬레이터에서 호스트 API에 접근할 주소는 `http://10.0.2.2:8080/`입니다.
평문 HTTP는 Debug 빌드에서만 허용합니다.
현재 앱 화면에서 API 요청을 실행하지는 않습니다.

## 검사와 계약

```sh
make check
make api-test-db
make ios-check IOS_SIMULATOR='iPhone 18 Pro'
make android-check
```

`make api-test-db`는 실행한 개발 DB를 사용합니다.
CI에서는 격리한 PostgreSQL에 `TEST_DATABASE_URL`을 직접 지정합니다.
로컬·CI PostgreSQL은 같은 multi-platform 이미지 digest에 고정했습니다.
새 DB에서 같은 명령을 수행할 때 `TEST_DATABASE_URL`을 지정하면 `.env` 없이 실행할 수 있습니다.
일반 API 테스트는 DB 없이 실행할 수 있습니다.

OpenAPI 원본은 Rust 코드입니다.

```sh
make api-spec
make api-spec-check
```

세 프로젝트의 빌드는 각각 수행합니다.
공통 계약 변경은 세 프로젝트의 CI를 실행합니다.
문서만 변경하면 기존 저장소 검사를 실행합니다.
CI 마지막의 `Project checks`는 선택한 검사들의 결과를 모읍니다.
캐시 조건과 병렬 실행 구조는 [CI 구성](CI.md)에서 확인합니다.
Room이 생성한 스키마 JSON의 마지막 줄 형식은 생성기 출력을 유지합니다.

## 운영 템플릿

아래 명령은 구성만 검사합니다. 운영 서비스를 시작하지 않습니다.

```sh
API_DOMAIN=api.example.invalid \
DATABASE_URL=postgres://example:example@database.invalid/smallnext \
docker compose -f infra/production/compose.yaml config --quiet
```

API 이미지 빌드:

```sh
make api-image-build IMAGE_BUILD_ARGS=--no-cache
make api-image-check
```

운영 DB는 Compose에 포함하지 않습니다.
실제 배포에는 도메인, 관리형 DB, TLS 연결 조건, 비밀정보 제공 경로,
DB 백업·복구, 인증 구현, 이전 앱과의 API 호환 검증이 필요합니다.
현재 템플릿은 운영 배포 완료의 증거가 아닙니다.
이미지의 Rust·Debian 기본 이미지는 digest로 고정합니다.
Debian의 `apt-get` 패키지와 Android emulator·system image revision은 외부 저장소에서 갱신될 수 있습니다.
따라서 현재 구성은 검사의 재현성을 높이며 바이트 단위의 동일한 산출물을 보증하지 않습니다.
완전한 고정이 필요하면 승인된 SDK·패키지 스냅샷을 별도로 보관해야 합니다.

## 공식 자료

- [GRDB](https://github.com/groue/GRDB.swift)
- [Android 오프라인 우선 구조](https://developer.android.com/topic/architecture/data-layer/offline-first)
- [Room](https://developer.android.com/jetpack/androidx/releases/room)
- [AGP 9.4 호환 조건](https://developer.android.com/build/releases/agp-9-4-0-release-notes)
- [AGP 9 내장 Kotlin](https://developer.android.com/build/migrate-to-built-in-kotlin): `org.jetbrains.kotlin.android` 플러그인을 적용하지 않습니다.
- [Axum](https://docs.rs/axum/latest/axum/)
- [SQLx](https://github.com/transact-rs/sqlx)
- [utoipa](https://github.com/juhaku/utoipa)

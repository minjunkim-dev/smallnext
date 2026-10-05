# 외부 구성 요소와 권리 고지

자체 코드의 권리 방침은 [COPYRIGHT](COPYRIGHT.md)에 있습니다.
아래 구성 요소에는 해당 권리자의 라이선스가 적용됩니다. 이 목록은 그 조건을 변경하지 않습니다.

확인 기준: 2026-10-04의 소스와 잠금 파일. 출시 패키지의 전체 고지를 완료했다는 뜻은 아닙니다.

## 저장소에 포함된 도구

| 구성 요소 | 버전·위치 | 조건과 출처 |
| --- | --- | --- |
| Gradle Wrapper | 9.8.0, `apps/android/gradle/wrapper/gradle-wrapper.jar`, `gradlew`, `gradlew.bat` | Apache-2.0. JAR의 `META-INF/LICENSE`와 스크립트의 원래 고지를 유지합니다. [Gradle 라이선스](https://github.com/gradle/gradle/blob/v9.8.0/LICENSE) |

## iOS 의존성

| 구성 요소 | 잠금 버전 | 조건과 출처 |
| --- | --- | --- |
| GRDB.swift | 7.11.1, `b83108d10f42680d78f23fe4d4d80fc88dab3212` | MIT. Copyright 2015–2025 Gwendal Roué. [해당 커밋의 LICENSE](https://github.com/groue/GRDB.swift/blob/b83108d10f42680d78f23fe4d4d80fc88dab3212/LICENSE) |

## Rust API의 직접 의존성

Cargo.lock과 `cargo metadata --locked`의 패키지 메타데이터를 확인했습니다.
외부 소스는 이 저장소에 vendoring하지 않습니다.

| 구성 요소 | 잠금 버전 | 라이선스 | 출처 |
| --- | --- | --- | --- |
| axum | 0.8.9 | MIT | [tokio-rs/axum](https://github.com/tokio-rs/axum) |
| serde | 1.0.229 | MIT OR Apache-2.0 | [serde-rs/serde](https://github.com/serde-rs/serde) |
| serde_json | 1.0.151 | MIT OR Apache-2.0 | [serde-rs/json](https://github.com/serde-rs/json) |
| sqlx | 0.8.6 | MIT OR Apache-2.0 | [launchbadge/sqlx](https://github.com/launchbadge/sqlx) |
| tokio | 1.53.1 | MIT | [tokio-rs/tokio](https://github.com/tokio-rs/tokio) |
| tracing / tracing-subscriber | 0.1.44 / 0.3.23 | MIT | [tokio-rs/tracing](https://github.com/tokio-rs/tracing) |
| utoipa | 5.5.0 | MIT OR Apache-2.0 | [juhaku/utoipa](https://github.com/juhaku/utoipa) |
| http-body-util / tower (개발용) | 0.1.5 / 0.5.3 | MIT | [hyperium/http-body](https://github.com/hyperium/http-body), [tower-rs/tower](https://github.com/tower-rs/tower) |

## Android의 직접 의존성과 빌드 도구

버전 기준 파일은 `apps/android/gradle/libs.versions.toml`입니다.
아래 링크는 원래 라이선스 확인 위치입니다. 전이 의존성 전체의 고지를 완료한 목록은 아닙니다.

| 구성 요소 | 버전 | 조건과 출처 |
| --- | --- | --- |
| AndroidX Activity / Compose / Room / Test | Activity 1.12.4, Compose BOM 2026.09.00, Room 2.8.5, Test JUnit 1.3.0 / Runner 1.7.0 | Apache-2.0. [AndroidX 고지](https://android.googlesource.com/platform/frameworks/support/+/androidx-main/LICENSE.txt) |
| Retrofit / Gson converter | 3.0.0 | Apache-2.0. [Retrofit LICENSE](https://github.com/square/retrofit/blob/trunk/LICENSE.txt) |
| OkHttp | 4.12.0 | Apache-2.0. [OkHttp LICENSE](https://github.com/square/okhttp/blob/parent-4.12.0/LICENSE.txt) |
| Kotlin | 2.2.20 | Apache-2.0. [Kotlin 라이선스](https://github.com/JetBrains/kotlin/blob/v2.2.20/license/LICENSE.txt) |
| KSP | 2.3.2 | Apache-2.0. [KSP LICENSE](https://github.com/google/ksp/blob/main/LICENSE) |
| Android Gradle Plugin | 9.4.1 | Apache-2.0. [Android 빌드 도구 고지](https://android.googlesource.com/platform/tools/base/+/refs/heads/mirror-goog-studio-main/NOTICE) |
| JUnit (테스트용) | 4.13.2 | EPL-1.0. [JUnit LICENSE](https://github.com/junit-team/junit4/blob/r4.13.2/LICENSE-junit.txt) |

## 이미지·음악·폰트

현재 추적된 저장소 파일에는 별도의 이미지·음악·폰트 원본이 없습니다.
시스템 글꼴이나 SDK 사용 권한을 자체 코드의 권리로 주장하지 않습니다.
새 에셋을 추가할 때 원본 출처, 권리자, 라이선스, 원본 공개 허용 여부와 배포 고지를 함께 기록합니다.

## 출시 전 확인

출시 빌드가 사용하는 전이 의존성, 엔진·SDK와 포함 에셋을 다시 확인합니다.
각 라이선스가 요구하는 저작권 고지, 라이선스 전문, NOTICE와 필요한 소스 제공을 실제 배포물에 포함합니다.
이 문서의 링크만으로 배포물의 고지 의무를 충족했다고 보고하지 않습니다.

# 개발 검증용 요청·화면 시간

확정 범위는 [#114](https://github.com/minjunkim-dev/smallnext/issues/114)를 따른다.
실제 OAuth 품질·시간 검증은 [#115](https://github.com/minjunkim-dev/smallnext/issues/115)에서 수행한다.

## 실행 경계

계측은 기본 OFF다. iOS Debug 실행에 `-suggestion_timing YES`를 명시한다.
Release 앱과 Release Rust 서버는 계측을 제공하지 않는다.
OFF에서는 측정 헤더·파일·화면 표식을 추가하지 않는다.
사용자 화면에 내부 진단 문구를 추가하지 않는다.
Debug 계측 화면의 접근성 식별자는 `timing:<UUID>:<request_kind>:<outcome>`이다.
이 식별자는 실제 화면 관측을 대신하지 않는다.

앱은 임의 UUID를 `X-Smallnext-Timing` 헤더로 보낸다.
서버는 유효한 UUID를 받은 Debug 요청에만 `_timing` 응답 확장을 추가한다.
공개 요청·제안·OpenAPI 계약은 유지한다.
서버는 기존 HTTP 인증과 권한·예산 검사도 유지한다.
서버는 원문·thinking·사용자 식별자·비밀정보를 측정 자료에 넣지 않는다.

앱은 최근 16개 표본을 앱 컨테이너의 `Library/Caches/suggestion-timing.json`에 저장한다.
파일은 로컬 검증 자료다. 파일을 운영 로그나 Crashlytics로 전송하지 않는다.
파일 저장 실패는 진행 상태에 영향을 주지 않는다.
이전 실행의 파일은 남을 수 있다. 관측 자료는 UUID로 연결한다.

## 시간의 의미

| 값 | 경계 |
| --- | --- |
| `authMS` | iOS 토큰 획득 구간. 개발 HTTP는 `authApplicable=false`이고 시간은 누락한다. 모의 사용자 인증은 별도 구간이다. |
| `httpMS` | iOS 요청 전송부터 응답 본문 수신까지. HTTP 오류에도 해당 구간을 기록한다. |
| `applyMS` | 공급자 완료 후 DB 적용과 진행 상태 읽기. 화면 표시 시간이 아니다. |
| `buttonToApplyMS` | 버튼 명령 시작부터 DB 적용까지. 앱 프로세스의 단조 시계를 쓴다. |
| `server.generate_ms`, `server.check_ms` | 기존 생성·검사 호출 구간. 시작하지 못했거나 끝나지 못한 역할은 `null`이다. |
| `server.total_ms` | 서버 요청 핸들러 시작부터 응답 생성까지. 서버 프로세스의 단조 시계를 쓴다. 사용자 경로에서는 서버 인증과 DB 처리도 포함한다. |
| `transportQueueResidualMS` | `httpMS - server.total_ms`. 음수이거나 서버 표본이 없으면 누락한다. 전송·큐 대기 등의 잔여 시간이다. 순수 네트워크 시간이 아니다. |
| `screenUpperBoundMS` | 앱 상태 콜백으로 채우지 않는다. 실제 외부 관측 자료에서만 제공한다. |

HTTP 대기와 서버 시간을 더하지 않는다.
서로 다른 프로세스의 시각을 직접 빼지 않는다.
누락 값은 0초나 성공으로 바꾸지 않는다.
검사 통과와 실제 화면을 모두 확인한 `action`·`question`만 정상 표본이다.
실패·거부·불확실·취소·저장 실패는 별도 표본이다.
상태가 바뀐 요청의 늦은 결과는 새 화면 표식으로 붙이지 않는다.
첫 행동·축소·다음 행동·대체 요청·목표 준비는 실제 요청 종류로 기록한다.

## 모의 시뮬레이터 검증

1. [개발 DB](DEVELOPMENT.md#개발-db와-api)를 준비한다. 검증 전용 DB를 사용한다.
2. 저장소 루트에서 모의 CLI만 선택한 Rust 서버를 실행한다.

   ```sh
   PATH="$PWD/services/api/tests/fixtures/timing-cli:$PATH" \
     DATABASE_URL='postgres://smallnext:smallnext-local-only@127.0.0.1:55434/smallnext' \
     DEVELOPMENT_SUBSCRIPTION_AI=1 API_BIND_ADDRESS=127.0.0.1:58114 \
     cargo run --locked --manifest-path services/api/Cargo.toml --bin smallnext-api
   ```

3. 설치한 iOS 27.0 시뮬레이터를 지정해 별도 검증 scheme을 실행한다.

   ```sh
   xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme TimingValidation \
     -destination 'platform=iOS Simulator,name=iPhone 18 Pro' \
     -resultBundlePath work/timing-screen.xcresult \
     -onlyUsePackageVersionsFromResolvedFile CODE_SIGNING_ALLOWED=NO test
   ```

4. `xcresult`의 화면 사진과 텍스트 관측 자료를 확인한다.

테스트는 기존 목표를 삭제하지 않는다. 합성 목표를 하나 추가한다.
테스트는 OFF 목표 준비와 ON 첫 행동·축소 행동·확인 질문·실패 화면을 확인한다.
관측자는 자기 프로세스의 단조 시계를 사용한다.
관측 시간은 tap 이전부터 첫 결과 화면 사진을 얻을 때까지의 상한이다.
접근성 표식을 찾은 뒤 500ms를 기다린다. 같은 표식을 다시 확인하고 화면 사진을 얻는다.
화면 사진에 결과가 실제로 보이는지 확인한다. 전환 중 사진은 정상 표본으로 사용하지 않는다.
관측 자료에는 실제 최대 샘플 간격을 남긴다.
XCTest의 tap 대기·접근성 조회·화면 사진 처리도 상한에 포함한다.
관측 상한이 목표를 넘으면 실제 화면 시간이 목표 이내라고 추정하지 않는다.
서버 시간만으로 전체 응답 목표를 통과시키지 않는다.
모의 화면 결과는 실제 모델 지연이나 품질의 증거가 아니다.

Claude Code 구독 OAuth·`claude-haiku-5-5 / xhigh` 설정을 변경하지 않는다.
기능 플래그 기본 OFF와 #61 실기기 보류를 유지한다.
유료 API 호출·실기기·운영 배포는 수행하지 않는다.

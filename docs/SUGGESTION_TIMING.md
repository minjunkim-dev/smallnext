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

## 서버 없는 핵심 흐름 화면 회귀

`TimingValidation`의 `testLocalCoreFlowRestoresDraftThroughActionsAndRelaunch`와
`testLocalCoreFlowKeepsLearningAndPersonalGoalsSeparate`,
`testLocalCoreFlowRestoresInputBeforeGoalPreparation`,
`testLocalCoreFlowPreservesProgressDuringGoalManagement`는 Debug 고정 공급자만 사용한다.
새 검증 전용 simulator에서 네 테스트만 선택해 실행한다.
기존 목표가 있는 simulator는 사용하지 않는다. 같은 이름의 목표 선택을 섞지 않기 위해서다.

```sh
xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme TimingValidation \
  -configuration Debug -destination "platform=iOS Simulator,id=$simulator" \
  -resultBundlePath work/core-flow-screen.xcresult \
  -onlyUsePackageVersionsFromResolvedFile -skipPackageUpdates \
  -only-testing:SmallnextTimingUITests/ScreenTimingTests/testLocalCoreFlowRestoresDraftThroughActionsAndRelaunch \
  -only-testing:SmallnextTimingUITests/ScreenTimingTests/testLocalCoreFlowKeepsLearningAndPersonalGoalsSeparate \
  -only-testing:SmallnextTimingUITests/ScreenTimingTests/testLocalCoreFlowRestoresInputBeforeGoalPreparation \
  -only-testing:SmallnextTimingUITests/ScreenTimingTests/testLocalCoreFlowPreservesProgressDuringGoalManagement \
  CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- CODE_SIGNING_REQUIRED=NO test
```

실행 인수는 `ios_core_flow YES`, `user_server_ai NO`, `suggestion_timing NO`다.
`development_ai_url`을 지정하지 않는다. Rust 서버·DB·모델·OAuth·실제 인증은 필요하지 않다.
업무 목표의 완료·축소·되돌리기·보류·재개와 입력 초안 복구를 검사한다.
학습 목표와 개인 목표의 전환·선택 상태·입력 초안 복구도 검사한다.
첫 행동 전 입력 복구와 확인 질문→완료 조건 확인→첫 행동도 검사한다.
목표 문구 수정·중단 뒤 진행을 보존한다. 삭제 확인 취소와 명시적 확인 뒤 삭제를 구분한다.
삭제 대상은 해당 테스트가 새로 만든 UUID 포함 합성 목표 하나다. 다른 합성 목표의 초안은 보존한다.
화면 사진은 `xcresult`에 첨부한다. 시간 목표와 실제 모델 품질의 근거로 사용하지 않는다.
이 네 테스트만으로 모션·VoiceOver·큰 글자·실기기와 #49 전체 완료를 판정하지 않는다.
기능 플래그 기본값과 #61 실기기 보류는 유지한다.

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

## 35초 모의 정상 화면

[#122](https://github.com/minjunkim-dev/smallnext/issues/122)의 별도 관측이다.
기존 ON/OFF·행동·확인 질문·실패 관측은 10초 대기를 유지한다.
`testDelayedNormalMockScreen`만 버튼 직전부터 사진 확보까지 60초를 사용한다.
`SMALLNEXT_TIMING_DELAYED_TEST=1`을 지정하지 않으면 이 테스트는 건너뛴다.
서버 120초·사용자 앱 160초 차단값을 변경하지 않는다.

1. 실행 전에 담당자 `minjunkim-dev`, Git 제외 보관 위치, 자기 자료만 삭제하는 방법을 기록한다.
   종료 뒤 최대 30일 이내의 절대 삭제 기한을 기록한다.
   기존 #115 자료 기한 `2026-11-10 22:38:08 KST`를 연장하지 않는다.
2. 기존 `services/api/tests/fixtures/timing-cli/codex`를 private 실행 디렉터리에 복사한다.
   복사한 CLI 옆에 빈 파일 `delay-first-action`을 만든다.
   Rust 서버의 `PATH`는 이 디렉터리를 먼저 사용한다.
   새 검증 DB와 새 시뮬레이터만 사용한다.
3. `TimingValidation`을 빌드한다.
   생성한 `.xctestrun`의 테스트 환경에 `SMALLNEXT_TIMING_DELAYED_TEST=1`과 전용 서버 URL을 지정한다.
   `-only-testing:SmallnextTimingUITests/ScreenTimingTests/testDelayedNormalMockScreen`으로 1회 실행한다.
   실패 뒤 재실행하지 않는다. 자동 테스트 재시도를 켜지 않는다.
4. `xcresult`의 JSON 관측 자료와 PNG 결과 사진을 확보한다.
   JSON의 UUID를 앱 컨테이너 `Library/Caches/suggestion-timing.json`과 연결한다.
   PNG의 SHA-256을 JSON의 `evidence_sha256`과 비교한다.
   사진에서 `펜 다섯 개 정리하기`가 실제로 보이는지 직접 확인한다.
5. 실제 최대 관측 간격·안정화·불안정 표본 수·사진 누락·상한·종료 상태를 기록한다.
   사진 부재는 `missing`이다. UI 조회나 사진 처리로 60초를 넘으면 `time_exceeded`다.
   늦은 사진으로 시간 초과를 성공으로 바꾸지 않는다.

35초 대기는 `first_action`의 생성 결과 대기에만 적용한다.
목표 준비와 검사 단계는 기존 0.15초 대기를 유지한다.
생성·검사에 각각 35초를 넣지 않는다.
`calls.jsonl`은 복사한 CLI 옆에 역할·요청 종류·설정 대기·실제 대기를 기록한다.
이 경로는 고정 합성 응답만 반환한다. 모델과 OAuth 인증정보를 읽지 않는다.
실제 모델 호출·유료 호출·자동 재실행은 각각 0개로 확인한다.

접근성 표식과 예상 문구는 사진 확보의 보조 조건이다.
사진의 직접 확인이 끝나기 전에는 정상 화면 확인을 완료로 보고하지 않는다.
관측 상한에는 tap·UI 조회·500ms 안정화 요청·사진 처리·hash 계산이 포함된다.
최대 관측 간격에는 블로킹 조회와 사진 처리도 포함된다.
500ms 설정값을 실제 관측 간격으로 보고하지 않는다.
실제 OAuth 품질·모델 지연·시간 목표·출시 승인과 모의 화면 성공을 구분한다.

기존 연결 표본 분석과 새 관측 결과는 [#122 검증 기록](research/delayed-mock-screen-validation.md)에 기록한다.

## 승인된 첫 행동10·더 작게10 화면 측정

후보·독립 상태·순서·담당·삭제와 실행 승인은 [#111 최소 계획](https://github.com/minjunkim-dev/smallnext/issues/111#issuecomment-6409138337)을 따른다.
`scripts/screen_evaluation.py`는 해당5개 합성 목표×2회에만 적용한다. 기본 실행은 차단되며
명시적인 `run(..., approved_once=True)`가 필요하다. 기존 launch의9후보·8흐름 승인을 재사용하지 않는다.
실제 측정은 코드의 검증·독립 리뷰·병합과 main CI 완료 후 새 판으로만 실행한다.

1. `TimingValidation`을 고정 패키지로 빌드하고 새 `Smallnext111-<식별자>` iOS27.0 시뮬레이터에 설치한다.
   개발 URL 없이 빈 앱을 한 번 열어 DB 마이그레이션만 수행한다. 별도 QA PostgreSQL과 loopback Rust 서버를 사용한다.
   구독 로그인 상태·CLI 버전/hash·최종 소스·시뮬레이터·서버·빌드 설정과 사용자 승인 원문을 비공개 실행 자료에 기록한다.
2. `freeze`에 main checkout `work/` 아래의 **미사용 새 폴더**, 담당자·미래 종료 상한·삭제 방법,
   실제 CLI와 관측 실행 파일을 전달한다. 원래 결과·기한을 변경하지 않는다.
   `screen_observer.Observer`의 `preflight()`는 전용 시뮬레이터와 빈 목표 DB를 확인한다.
3. 전용 `codex` wrapper만 `oauth_bridge.py --screen-session <새 폴더> --output-mode text-json`을 호출한다.
   wrapper는 절대 경로의 승인 CLI·기록 위치를 사용한다. Rust의 기존120초·앱160초를 유지한다.
   bridge는 현재 슬롯의 고정 입력과 생성→검사 순서, 후보 동일성·모델/사용량·8192 설정·취소/정리를 확인한다.
4. `run`은 기존 평가와 같은 `launch-model.lock`을 소유하며 새 run-started를 한 번만 기록한다.
   `Observer`는 새 합성 목표만 추가하고 첫 행동용 준비 상태 또는 축소용 미완료 현재 행동을 복원한다.
   모델 목표 준비나 사용자 수행/완료 기록은 만들지 않는다. 입력은 기존 Swift HTTP 전송 결과와 정확히 대조한다.
5. `testApprovedSingleScreen`만 선택한다. 테스트 환경의 `SMALLNEXT_SCREEN_ONCE=1`, 요청 종류와 전용 URL을 지정한다.
   기존 관측자의 단조 시계·500ms 안정화·UUID·사진/hash를 사용하며 이번 관측만180초다.
   `xcresult`를 즉시 추출하고 해당UUID의 앱/서버 계측과 원래 모델 출력을 **다음 요청 전에** 저장한다.
   최근16개 캐시를 마지막에 한 번만 복사하지 않는다. 기존 모의10초/60초 테스트는 유지한다.
6. 총20요청·생성20+검사20=40역할·연속60분을 넘지 않는다. 실행기의 전체 시계는 첫 슬롯 준비 직전부터
   보관까지 포함하므로 버튼 시작 기준보다 보수적이다. 생성 시작부터 검사 완료까지 합계120초다.
   오류·품질 거부/불확실·기록 누락·상한에서는 전체 종료한다. 재시도·재개·대체/보충·warm-up 호출은 없다.
   QA 앱 종료로 HTTP를 끊고 bridge는 소유권 상실 시 CLI를 종료·회수한다.
7. 사진을 실제 확인한 뒤 해당hash의 `samples/NN-review.json`에 `basis=agent_pixel_review`,
   `visible_normal_result=true/false`를 새로 기록한다. 원래 사진/관측 자료는 수정하지 않는다.
   `report`는 직접 사진 확인 전 표본을 정상 통계에 넣지 않는다. 에이전트 화면 검토는 사용자 직접 판정과 구분한다.

종류별 정상10개 미만은 p90 미확인이다. 중앙값20초·p90 30초를 넘은 느린 정상 결과도 그대로 포함한다.
관측 상한과 실제 최초 픽셀 시각을 구분하며, 이 합성20표본으로 일반 사용자 분포·출시 준비를 판정하지 않는다.
종료 후30일과 동결 때 고정한 삭제 상한 중 이른 시각을 사용한다. 파일0600·폴더0700을 유지한다.
검증에는 가짜 CLI/시계/사진과 합성 DB만 사용한다. 실제 호출 전에는 기존 평가 결과를 재생해 화면 표본으로 세지 않는다.

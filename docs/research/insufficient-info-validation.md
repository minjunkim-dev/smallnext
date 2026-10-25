# 정보 부족·보충 입력의 합성 검증

2026-10-24 KST, [#278](https://github.com/minjunkim-dev/smallnext/issues/278)의 검증 기록입니다. 정책 정본은 [#271](https://github.com/minjunkim-dev/smallnext/issues/271)과 그 사양이 연결한 [#267](https://github.com/minjunkim-dev/smallnext/issues/267#issuecomment-6359424978)·[#268](https://github.com/minjunkim-dev/smallnext/issues/268#issuecomment-6366338459)입니다. 이 문서는 정책을 다시 정하지 않습니다.

## 기준과 재사용

기준 main은 `719a71c651a3789e5a97c8e82ab26ea9364309e2`입니다. #273~#277는 각각 [#279](https://github.com/minjunkim-dev/smallnext/pull/279)·[#280](https://github.com/minjunkim-dev/smallnext/pull/280)·[#281](https://github.com/minjunkim-dev/smallnext/pull/281)·[#282](https://github.com/minjunkim-dev/smallnext/pull/282)·[#283](https://github.com/minjunkim-dev/smallnext/pull/283)으로 병합됐습니다. #283의 최종 head `9700164aed4aaa004dabffe0c9fa0ee53bfb8b11`과 기준 main의 tree는 같습니다.

제품 코드·설정은 그 상태를 유지합니다. 이번 변경은 누락된 시뮬레이터 삭제/자동 초점 사례, #267의 세 공유 입력/후보/고정 판정, 기존 앱·서버 경계의 대조와 이 기록입니다. 아래 기존 실행을 재사용하고, 공유 사례가 바뀐 core/server와 저장소 필수 검사는 최종 변경에서 갱신합니다. 실행 ID는 `agent_workflow.py` 기록이며 GitHub run ID와 구분합니다.

| 식별자 | 실행·결과 | 출처 |
| --- | --- | --- |
| core | `df66d408e6d14ec386b07cc669ad16a5`: Swift core 126개 통과. 가짜 공급자·개발/사용자 전송 대역·실제 임시 SQLite | #283 |
| server | `e737aed025b040f78ccd46b7273cef58`: Python337개(기존 skip1), Rust fmt/clippy/전체·OpenAPI, 격리 PostgreSQL의 서버 HTTP20개 통과 | #283 |
| host | `0a2418eb12f24016be9d69fa3300d5b3`: 앱 호스트34개 중 기존 skip1·실패0, 기존 첫 행동 UI2개 통과 | #283 |
| four-ui | `aada3b8025f14969bab2a10d3ea3a544`: 질문 답 복구 → 안내 → 보충 저장/복구 → 명시적 재요청 → 행동/완료 개수 복구. 네 종류 전체 통과, 219.328초 | #283 |
| storage-ui | `8c96498b55994fbea98a22403a60e319`: 초안·확인 저장·재실행·큰 글자 편집·목표 목록 복귀, 저장/복구 추가 호출0 | #281 |
| source-cases | `testSharedSourceDecisionsPreserveProgressOnBothAdapters`: 공유9사례를 개발/사용자 전송·실제 SQLite에서 대조. 정확한 입력 맥락, 정상 안내/실제 질문/거부/불확실·자동 복구0·요청1·행동/완료0 확인. 서버는 같은 후보의 G1/C1·판정·공개 후보 유무 확인. 최종 실행 ID는 PR에 기록 | 이번 변경 |
| delete-ui | `55c8a07cbd2b4122a6fa6dbd465a4cc2`: 새 삭제/자동 초점 UI1개 통과, 69.375초. 같은 이름의 두 목표 생성 후 추가 HTTP 요청0 | 이번 변경 |

이전 UI의 실패도 보존합니다. #283 첫 실행은 smaller의 ‘돌아가기’ 뒤 같은 목표를 탭하면 안내가 다시 열린다고 잘못 기대했습니다. 기존 동일 목표 선택 no-op/재실행 복구 계약에 맞춰 기대를 수정한 뒤 four-ui를 통과했습니다. 실제 제품 결함인 오래된 화면의 다른 목표 전송은 별도 재현 후 #283에서 수정했습니다. 이번 delete-ui는 첫 실행에 통과했습니다. 최초 Spec 리뷰가 #267의 세 명시적 후보 누락을 찾아 아래 source-cases로 보완했습니다. 새 Swift 검사 작성 중 없는 필드를 참조한 컴파일 실패와 HTTP 대역 안의 XCTest/actor 격리 실패가 있었으며 화면 판정으로 수정하고 단언을 사용자 명령 완료 뒤로 옮겨 통과했습니다. 이 실패는 제품 동작 실패와 구분합니다.

## 12개 기대 결과 대조

아래 표는 #271~#283 당시 합성 검증의 이력이다. #313 이후 새 평가 입력·기대값은 [현재 자료 확인·기록 상태](oauth-quality-evaluation.md#313-이후-자료-확인기록-상태)를 따른다.
특히 당시 상충 사례의 `uncertain`은 이력으로 보존하며, 새 평가의 `conflicting-sources`는 정리할 중간 결과가 남아 `reject`를 기대한다. 과거 평가를 소급 변경한 결과가 아니다.
서버·앱의 `uncertain` 전송/진행 보존은 별도 명시적 실패 회귀로 계속 검사한다.

`F/N/S/R`은 `first_action/next_action/smaller/replacement`입니다. 앱 호출 수는 HTTP/공급자 요청 수, 서버의 `G/C`는 생성/독립검사 역할 수입니다. 아래 status는 합성 응답의 기대값이며 실제 의미 품질 판정이 아닙니다.

| #271 행 | 요청·기대 status | 진행·호출 수 | 검사와 실행 근거 |
| --- | --- | --- | --- |
| 1. 네 종류 안내 | F/N/S/R: `accepted + insufficient_info` | 행동/완료조건 빈 문자열·0분, 남은 작업/완료 ID의 순서와 완료 플래그 보존. 앱1, G1/C1 | 공유 fixture `response`, `testSharedInsufficientInfoIsAValidTransportResponse`, `insufficient_info_crosses_http_with_independent_checks_and_no_failure_conversion`; core/server/four-ui |
| 2. 준비·legacy·필드 오류 | 준비/legacy는 새 status 거부, 미지원 종류는 `invalid_input`, 필드 오류는 `invalid_proposal` | 생성 전 입력 오류 G0/C0, 생성 구조 오류 G1/C0. 진행 미적용 | `invalid_insufficient_info_never_starts_checker`, `testInsufficientInfoRejectsMalformedFieldsAndGoalPreparation`, `testCandidateTypeMustMatchRequestKind`; server/core |
| 3. 실제 질문·대안 없음 | F/N/S/R: `need_info`, R만 `no_action` | 질문 답은 원래 종류로1회, R 보류 유지. 유효 응답 G1/C1, 다른 종류 no_action G1/C0 | 공유 `question/supplemental_question`, `testActionQuestionsRestoreDraftAndSubmitOnceWithOriginalKind`, `testHTTPNewInformationPreservesOriginalQuestionsBlockerAndProgressOnBothAdapters`; core/server/four-ui |
| 4. 성급한 정보 부족 | `useful-source-check/real-unanswered-question`: `rejected`, 상충 사례는 `uncertain` | 후보 없음, 진행 유지, G1/C1. 실패를 정상 안내로 바꾸지 않음 | source-cases와 공유 `checker_cases`, `insufficient_info_is_checked_without_creating_an_action`, 서버 HTTP 동일 사례; server, 앱의 rejected/uncertain 전송·진행 회귀는 core |
| 5. 출처·미기재·자기 진술 | 아래 사례표의 accept/reject/uncertain 분리 | 보존 필드 유지, facts/reduction 공개 제거, G1/C1 | 공유 `checker_cases`, `supplemental_first_action`; server/core. 사실의 진위·실제 모델 판정은 미수행. source-cases는 아래 명시적 후보도 대조 |
| 6. 초안·확인 저장·복구 | 정상 안내와 원래 진행 유지 | 저장/복구0, 원래 목표/막힘/완료/보류 불변, 목표별 격리 | `testSupplementalDraftAndConfirmationRestoreSeparatelyWithoutCallingProvider`, `testSupplementalInputPreservesOriginalContextProgressAndSameNamedGoalOnDeletion`; core/storage-ui |
| 7. 신규·동일·공백·되돌림 | F/N/S/R: 유효한 새 입력만 원래 종류 재요청 | 명시적 신규1, 동일/공백/초안/원복0, 새 요청 ID | `testAllReproposalsIgnoresWhitespaceDraftsAndRevertedInformation`, `testSupplementalReproposalResumesOriginalKindWithoutRepeatingProgress`; core/four-ui |
| 8. 중복·취소·상태 변경 | F/N/S/R: 기존 상태의 요청/늦은 결과 미적용 | 중복 추가0, 취소/목표/진행/확인정보 변경 후 진행·입력 보존 | `testAllReproposalsRechecksPendingBeforeCallingProvider`, `testAllReproposalsLateResultsNeverOverrideChangedOrInterruptedProgress`, 오래된 목표·smaller 행동 회귀; core |
| 9. 재안내·실패·복구 | F/N/S/R: 정상 안내·need_info·통신/형식/reject/uncertain 구분 | 재안내 후 자동0, pending 복구 interrupted/자동0. 실패는 마지막 정상 안내 유지 | `testHTTPNewInformationPreservesOriginalQuestionsBlockerAndProgressOnBothAdapters`, `testFirstReproposalFailureKeepsNoticeAndRequiresSeparateManualRetry`; core/server/four-ui |
| 10. 실패·크기·다국어 | 입력/HTTP 본문 UTF-8 32KiB, 막힘 2,048바이트 | 초과/잠금/저장 실패 시 공급자0, 편집·기존 저장·남은 범위 유지, 자동 절단 없음 | `testSupplementalByteLimitAndStorageFailuresKeepSavedValuesAndPreventNavigation`, `testAllReproposalsOversizedInputPreservesConfirmedTextDraftAndNotice`, `testConfirmedSupplementalRespectsWholeHTTPBodyAndBlockerByteLimits`; core/server |
| 11. 삭제·같은 이름 | 확인한 목표의 보충/초안/안내만 삭제 | 삭제 실패 원자성·취소 보존, 다른 목표/외부 원본 불변, 추가 호출0 | `testSharedHTTPNoticeAndMetadataStayIsolatedAndDeleteAtomically`, `testSupplementalFocusAndDeletionKeepSameNamedGoal`; core/delete-ui |
| 12. OFF/로컬 ON·구버전 | 기본 OFF, 테스트 ON에서 새 합성 응답, 미지원 후보 거부 | OFF 인증/공급자0. 새 상태를 임의 행동으로 바꾸지 않음 | `FeatureFlagsTests`, 앱 `FeatureFlagsBundleTests`, `off_user_ai_route_cannot_start_authentication_or_provider`, 아래 호환 확인; core/server/host |

앱 검사는 [ProgressFlowTests](../../apps/ios/Packages/SmallnextCore/Tests/SmallnextCoreTests/ProgressFlowTests.swift)·[DevelopmentAITests](../../apps/ios/Packages/SmallnextCore/Tests/SmallnextCoreTests/DevelopmentAITests.swift), 서버 검사는 [공유 파이프라인](../../services/api/src/suggestion/tests.rs)·[사용자 HTTP](../../services/api/src/user_ai/tests.rs)에 있습니다. 두 전송 어댑터 회귀는 같은 실제 입력/응답 JSON·원래 질문답/막힘/보충/진행과 호출 수를 대조합니다. source-cases는 각 공유 입력의 제공 사실을 GoalInput.currentState로 사용자 경로에 넣고, 판정·정상 후보·실패의 저장/재실행 결과를 확인합니다. 거부 후보는 서버 공개 응답에서 이미 제거하므로 앱에는 disposition만 전달합니다.

## #267/#268의 출처 경계

[공유 사례](../../contracts/fixtures/insufficient-info.json)의 `checker_cases`를 공유 파이프라인과 서버 HTTP가 함께 사용하며 앱 source-cases도 같은 입력 맥락/공개 판정을 사용합니다. 가짜 검사기의 판정을 미리 고정해 전달·적용 경계를 검사합니다. 호스트가 자연어 의미나 실제 과거 사실을 판정했다는 증거가 아닙니다.

| 사례 ID | 입력의 차이·고정 결과 | #267/#268 연결 |
| --- | --- | --- |
| `no-source-or-answer` | 자료/기억/새 답 모두 없음 → `accepted/insufficient_info` | 실제로 유용한 행동·질문이 없을 때 정상 안내 |
| `useful-source-check` | 직접 고른 메일과 미기재라는 유용한 확인 결과가 남음 → 성급한 안내 `rejected` | 자료 존재와 내용의 확인 구분 |
| `real-unanswered-question` | 자료 유무를 아직 묻지 않음 → 안내 `rejected`, 별도 공유 question은 `need_info` | 자료 유무라는 실제 미답 질문을 먼저 함 |
| `conflicting-sources` | 참여자/책임자 기록이 상충하고 참값 모름 → `uncertain` | 상충을 확신 있는 정상 후보로 바꾸지 않음 |
| `source-omission-is-not-absence` | 선택한 회의록의 미기재를 확인, 실제 역할은 모름 → `accepted/insufficient_info` | 자료 범위의 미기재를 과거 사실의 부재로 바꾸지 않음 |
| `memory-without-details` | 기억한다고만 한 입력, 실제 한 일 한 가지를 묻는 명시적 `need_info` 후보 → `accepted` | 기억만으로 과거 사실을 채우지 않고 필요한 실제 질문을 제공 |
| `known-unknown-rewrite` | 이미 기록한 모름을 다시 적는 명시적 `action` 후보 → `rejected/기준4` | 새 확인·유용한 결과 없는 재기록은 충분하지 않음 |
| `unsupported-fill-in` | 자료/경험이 없는 입력, 책임자로 팀을 이끌었다고 채워 쓰라는 명시적 `action` 후보 → `rejected/기준3` | 사용자 작성/빈칸이라는 이유로 필요한 과거 사실의 근거가 생기지 않음 |
| `specific-user-statement` | 일정 조율 경험을 구체적으로 제공 → 성급한 안내 `rejected` | 구체적 자기 진술은 제공 사실로 받음. `supplemental_first_action`도 사용자 진술 표시·외부 검증 미확인 전송을 검사 |

세 고정 후보의 거부/수용 전달을 확인했지만 사실 창작·빈칸 작성·알려진 모름의 재기록이 실제 모델에서 배제되는지는 [#111](https://github.com/minjunkim-dev/smallnext/issues/111)·[#47](https://github.com/minjunkim-dev/smallnext/issues/47)의 별도 직접 평가에 남깁니다. facts 요약 누락 자체와 진행 보존 실패를 혼동하지 않습니다. #265의 기존99흐름·직접 판정·보관 상한을 새 계약의 품질 통과로 올리지 않습니다.

## 화면·접근성과 호환

Xcode27.1 `27A9275`, arm64, iPhone18 Pro/iOS27.0입니다. 기존 four-ui의 네 종류 화면16개·접근성 트리8개와 storage-ui의 큰 글자 입력을 재사용해 제목→본문→조작 순서, 실제 질문 답 복구, 돌아가기, 저장 후 이전 안내, 명시적 재요청과 완료 개수를 확인했습니다. 대표 화면은 아래에 보존합니다.

| 정상 안내(#283) | 저장 후 이전 안내·명시적 재요청(#283) | 큰 글자 편집(#281) |
| --- | --- | --- |
| [화면](fixtures/insufficient-info-notice.png) | [화면](fixtures/insufficient-info-supplemental.png) | [화면](fixtures/insufficient-info-large-text.png) |

이번 `testSupplementalFocusAndDeletionKeepSameNamedGoal`은 편집창을 탭하지 않고 입력해 키보드 자동 초점을 확인했습니다. 삭제 취소 뒤 편집 중 텍스트를 유지하고, 삭제 확인 뒤 같은 이름의 다른 목표만 남아 재실행 후 보충 입력을 복구합니다. 초기 목표 준비2·첫 행동2 외 추가 HTTP 요청0, 실제 모델0입니다. [취소 후 초안](fixtures/insufficient-info-delete-cancelled.png)·[다른 목표 복구](fixtures/insufficient-info-same-name-retained.png)를 저장했습니다. 취소 화면에는 시뮬레이터의 최초 키보드 안내가 함께 보이며 입력값은 확인 가능합니다.

이번 UI 응답은 임시 localhost HTTP 대역이 기존 `services/api/tests/fixtures/timing-cli/codex`를 실행해 반환했습니다. 생성/독립검사·DB 서버 증거는 별도 server 실행을 재사용하며 이 UI 대역으로 대체하지 않습니다. 접근성 트리·레이블/힌트·컨테이너 순서·소스의 접근성 초점과 시뮬레이터 키보드 조작을 확인했으며 실제 VoiceOver 읽기·스위치 제어·실기기 접근성 통과는 주장하지 않습니다.

`user_server_ai` 기본 OFF와 테스트 ON을 구분합니다. UI는 `ios_core_flow=YES`, `user_server_ai=NO`, 개발 합성 URL을 명시합니다. 사용자용 경로의 로컬 ON은 가짜 인증/원격 모델과 실제 격리 DB의 server/core 전송 검사입니다. 실제 인증을 ON으로 실행한 것이 아닙니다. 구독 어댑터의 합성 CLI5개와 compact 공유 fixture 호환은 #282/#283에서 통과했습니다.

구버전 기준 `840b190ddac262cb909540c7b3280b4da84c3f5c`의 HTTP 변환기는 빈 행동/완료조건을 거부하고 미지원 status의 default에서도 rejected를 반환합니다. 이번에 그 원문을 확인했고 현재 `testInsufficientInfoRejectsMalformedFieldsAndGoalPreparation`의 future_status 회귀 및 실패 시 진행 보존 근거를 대조했습니다. 구버전 앱 바이너리를 별도로 설치·실행하지는 않았습니다.

## 재현과 미수행

검사는 항상 `python3 ~/.agents/tools/agent_workflow.py check -- <명령>`으로 하나씩 실행합니다. 기존 두 경계의 전체 명령은 #283에 있습니다. 이번 추가 사례는 `swift test --package-path apps/ios/Packages/SmallnextCore --force-resolved-versions`와 `make check`, 격리 TEST_DATABASE_URL의 `cargo test --locked --manifest-path services/api/Cargo.toml --lib user_ai -- --ignored`로 갱신합니다. UI를 다시 재현할 때는 [개발 절차](../DEVELOPMENT.md)의 격리 DB·개발 HTTP에 위 timing-cli를 PATH 맨 앞에 선택하고 빈 전용 CODEX_HOME을 사용합니다. 실제 선택 경로를 확인한 뒤 localhost `127.0.0.1:58114`에서 합성 서버만 실행합니다. OAuth·실제 모델을 시작하지 않습니다.

```sh
python3 ~/.agents/tools/agent_workflow.py check -- xcodebuild \
  -project apps/ios/Smallnext.xcodeproj -scheme TimingValidation \
  -destination 'platform=iOS Simulator,id=<전용 iOS27.0 시뮬레이터 ID>' \
  -onlyUsePackageVersionsFromResolvedFile -skipPackageUpdates \
  CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- CODE_SIGNING_REQUIRED=NO \
  -resultBundlePath work/278/reproduction.xcresult \
  -only-testing:SmallnextTimingUITests/ScreenTimingTests/testSupplementalFocusAndDeletionKeepSameNamedGoal test
```

최종 head·로컬 최소 검사·독립 리뷰·새 필수 CI/Trusted CI와 병합 후 main 근거는 #278에 연결한 PR에 기록합니다. 기존 합성 결과의 재사용과 이번 head의 CI를 구분합니다. 실제 모델·OAuth/구독 평가 재실행·API 비용/지연·실기기·운영 배포·출시 판단은 미수행이며 #111/#47에 남깁니다. #47 OPEN·#61 실기기 보류·모든 플래그 기본 OFF를 유지합니다.

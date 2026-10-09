# iOS Crashlytics 개발 검증

범위와 완료 조건은 [#80](https://github.com/minjunkim-dev/smallnext/issues/80)에서 관리합니다.
검사 결과와 남은 콘솔 확인도 해당 Issue에 기록합니다.

## 실행과 전송

`ios_crash_reporting`의 기본값은 [등록 파일](../config/feature-flags.json)에서 확인합니다.
현재 기본값은 OFF입니다. Debug 실행 인자로만 로컬 ON을 허용합니다.
Release에서는 실행 인자로 플래그를 바꾸거나 합성 크래시를 발생시킬 수 없습니다.

OFF에서는 기본 FirebaseApp을 초기화하지 않습니다.
ON에서는 서버 AI와 별도로 기본 FirebaseApp과 Crashlytics를 시작합니다.
서버 AI의 `SmallnextUserAI` 인증 인스턴스는 유지합니다.
Google Analytics와 breadcrumb 수집은 연결하지 않습니다.
목표, 답변, AI 원문, 토큰, UID를 custom log, custom key, user ID로 보내지 않습니다.
Crashlytics는 SDK의 기기·앱·스택 정보를 수집합니다.

Debug·Release의 `FirebaseCrashlyticsCollectionEnabled`와 `FirebaseDataCollectionDefaultEnabled`는 false입니다.
ON 실행은 자동 수집을 켜지 않고 `sendUnsentReports()`로 저장된 보고서만 보냅니다.
`setCrashlyticsCollectionEnabled(true)`는 다음 실행에도 남으므로 사용하지 않습니다.
이 경로는 개발 검증용입니다. 출시 수집·동의 정책은 별도로 결정합니다.

Firebase 공개 클라이언트 설정은 [SERVER_AI](SERVER_AI.md#ios-연결)와 같은 네 항목을 사용합니다.
API 서버 주소와 AI 플래그는 필요하지 않습니다.
설정이 누락되거나 형식이 잘못되면 Firebase를 초기화하거나 보고서를 보내지 않습니다.
유효한 형식의 앱 ID·키가 실제 프로젝트와 일치하는지는 콘솔에서 확인합니다.

## 빌드와 심볼

저장소 루트에서 실행합니다. `config.xcconfig`에는 로컬 공개 클라이언트 설정을 넣습니다.
공개 설정을 포함한 파일도 Git에 추가하지 않습니다.
이 예시는 DerivedData 내부의 기본 SPM 캐시를 사용합니다.

```sh
xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme Smallnext \
  -configuration Debug -destination 'platform=iOS Simulator,id=<UDID>' \
  -derivedDataPath /tmp/smallnext-crashlytics -xcconfig config.xcconfig \
  -onlyUsePackageVersionsFromResolvedFile CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- \
  SMALLNEXT_UPLOAD_CRASHLYTICS_SYMBOLS=YES build
```

Debug·Release 모두 dSYM을 생성합니다.
업로드 빌드 설정의 기본값은 NO입니다. 일반 빌드와 CI에서는 업로드하지 않습니다.
명시적인 YES 빌드만 SDK의 `upload-symbols -ai ... -p ios`를 동기 실행합니다.
업로드 실패는 빌드를 실패시킵니다. Firebase app ID는 빌드한 Info.plist에서 읽습니다.
업로드 성공은 콘솔의 크래시 수신이나 프레임 심볼화를 증명하지 않습니다.

시뮬레이터의 실제 SDK 검증은 로컬 서명을 사용합니다. Apple 유료 멤버십은 필요하지 않습니다.
시뮬레이터 전용 `application-identifier`는 앱의 bundle ID를 사용합니다.
이 설정은 실기기와 스토어 빌드에 적용하지 않습니다.
서명 없는 CI 테스트에서는 Firebase를 시작하지 않습니다.
서명 없는 앱은 Firebase Installations의 Keychain 접근에서 `-34018`로 실패할 수 있습니다.
오류 근거는 [Apple의 Keychain entitlement 설명](https://developer.apple.com/forums/thread/114456)입니다.

## 시뮬레이터 합성 크래시

SDK를 연결한 Debug 앱을 설치한 뒤 실행합니다.
기존 앱 데이터는 삭제하지 않습니다. Xcode 디버거를 연결하지 않습니다.

1. `xcrun simctl launch <UDID> dev.smallnext.app -ios_crash_reporting NO`로 OFF 실행을 확인합니다.
2. 아래 명령으로 ON 앱을 실행합니다. 앱은 3초 뒤 고정 메시지로 크래시를 발생시킵니다.
3. 합성 크래시 인자 없이 아래 재실행 명령을 실행합니다. 저장된 보고서를 보냅니다.
4. Firebase 콘솔의 iOS 앱에서 테스트 크래시와 앱 프레임 심볼화를 확인합니다.
5. 앱을 종료한 뒤 OFF 명령으로 재실행합니다.

```sh
# 합성 크래시. 실제 목표나 답변은 사용하지 않습니다.
xcrun simctl launch --terminate-running-process <UDID> dev.smallnext.app \
  -ios_crash_reporting YES -crashlytics_test_crash YES -FIRDebugEnabled
# 재실행하여 전송합니다. 크래시 인자를 제거합니다.
xcrun simctl launch <UDID> dev.smallnext.app \
  -ios_crash_reporting YES -FIRDebugEnabled
# OFF 복귀
xcrun simctl launch --terminate-running-process <UDID> dev.smallnext.app \
  -ios_crash_reporting NO
```

콘솔 수신에는 수 분이 걸릴 수 있습니다.
SDK 전송 로그, 심볼 업로드, 콘솔 수신, 앱 프레임 심볼화는 각각 확인합니다.
콘솔을 확인할 수 없으면 #80을 열린 상태로 유지합니다.

공식 근거: [시작과 테스트 크래시](https://firebase.google.com/docs/crashlytics/ios/get-started),
[자동 수집과 수동 전송](https://firebase.google.com/docs/crashlytics/ios/customize-crash-reports).

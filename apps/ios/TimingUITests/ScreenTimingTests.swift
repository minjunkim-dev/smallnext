import XCTest
import CryptoKit

/// 별도 TimingValidation scheme에서 고정 공급자 또는 모의 Rust 서버와 실행한다.
@MainActor
final class ScreenTimingTests: XCTestCase {
    func testLocalCoreFlowRestoresDraftThroughActionsAndRelaunch() {
        continueAfterFailure = false
        let app = localApp()
        startLocalGoal(app, goal: "분기 업무 보고서 초안 쓰기", firstAction: "업무 보고서 문서 하나 열기")
        app.buttons["완료"].tap()
        let nextAction = "이번 분기에 끝낸 업무 하나 적기"
        XCTAssertTrue(app.staticTexts[nextAction].waitForExistence(timeout: 10))
        let draft = "분기 보고서 검증 메모"
        app.textFields["행동 결과 입력"].tap()
        app.textFields["행동 결과 입력"].typeText(draft)
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, draft)

        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts[nextAction].waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, draft)
        XCTAssertNotNil(attach(app, name: "local-core-restored-draft"))

        app.buttons["더 작게"].tap()
        XCTAssertTrue(app.staticTexts["첫 부분만: \(nextAction)"].waitForExistence(timeout: 10))
        app.buttons["더 보기"].tap()
        app.buttons["되돌리기"].tap()
        XCTAssertTrue(app.staticTexts[nextAction].waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, draft)
        XCTAssertNotNil(attach(app, name: "local-core-undo"))

        app.buttons["더 보기"].tap()
        app.buttons["나중에"].tap()
        XCTAssertTrue(app.staticTexts["목표에 대해 떠오르는 생각 한 줄 적기"].waitForExistence(timeout: 10))
        app.buttons["더 보기"].tap()
        app.buttons["나중에"].tap()
        XCTAssertTrue(app.staticTexts["보류 중"].waitForExistence(timeout: 10))
        XCTAssertNotNil(attach(app, name: "local-core-on-hold"))
        app.buttons["재개: \(nextAction)"].tap()
        XCTAssertTrue(app.staticTexts[nextAction].waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, draft)
        XCTAssertNotNil(attach(app, name: "local-core-resumed-draft"))
    }

    func testLocalCoreFlowKeepsLearningAndPersonalGoalsSeparate() {
        continueAfterFailure = false
        let app = localApp()
        let learning = "통계 기초 단원 하나 학습하기"
        let personal = "개인 프로젝트로 베란다 화분 옮겨 심기"
        startLocalGoal(app, goal: learning, firstAction: "학습 자료에서 다음 단원 열기")
        app.textFields["행동 결과 입력"].tap()
        app.textFields["행동 결과 입력"].typeText("학습 메모")
        startLocalGoal(app, goal: personal, firstAction: "옮길 화분 하나 정하기")
        app.textFields["행동 결과 입력"].tap()
        app.textFields["행동 결과 입력"].typeText("화분 메모")

        selectLocalGoal(app, goal: learning)
        XCTAssertTrue(app.staticTexts["학습 자료에서 다음 단원 열기"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, "학습 메모")
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["학습 자료에서 다음 단원 열기"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, "학습 메모")
        XCTAssertNotNil(attach(app, name: "local-core-learning-restored"))

        selectLocalGoal(app, goal: personal)
        XCTAssertTrue(app.staticTexts["옮길 화분 하나 정하기"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, "화분 메모")
        XCTAssertNotNil(attach(app, name: "local-core-personal-restored"))
    }

    func testLocalCoreFlowRestoresInputBeforeGoalPreparation() {
        continueAfterFailure = false
        let app = localApp()
        newGoal(app)
        app.textFields["목표 한 문장"].tap()
        app.textFields["목표 한 문장"].typeText("정리하기")
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["목표 목록"].waitForExistence(timeout: 10))
        newGoal(app)
        XCTAssertEqual(app.textFields["목표 한 문장"].value as? String, "정리하기")
        app.buttons["목표 정리"].tap()
        let answer = app.textFields["목표 확인 질문 답"]
        XCTAssertTrue(answer.waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["확인하고 시작"].exists)
        XCTAssertNotNil(attach(app, name: "local-core-preparation-question"))
        answer.tap()
        answer.typeText("집 책상 위 물건을 정리해요.")
        app.buttons["답 보내기"].tap()
        XCTAssertTrue(app.buttons["확인하고 시작"].waitForExistence(timeout: 10))
        XCTAssertFalse(answer.exists)
        XCTAssertNotNil(attach(app, name: "local-core-preparation-summary"))
        app.buttons["확인하고 시작"].tap()
        XCTAssertTrue(app.staticTexts["목표와 관련된 첫 자료 하나 열기"].waitForExistence(timeout: 10))
        XCTAssertNotNil(attach(app, name: "local-core-preparation-first-action"))
    }

    func testLocalCoreFlowPreservesProgressDuringGoalManagement() throws {
        continueAfterFailure = false
        let app = localApp()
        let runID = UUID().uuidString
        let original = "목표 관리 검증 \(runID)"
        let retained = "보존할 검증 목표 \(runID)"
        let firstAction = "목표와 관련된 첫 자료 하나 열기"
        let nextAction = "연 자료에서 지금 할 한 가지를 고르기"
        startLocalGoal(app, goal: original, firstAction: firstAction)
        app.buttons["완료"].tap()
        XCTAssertTrue(app.staticTexts[nextAction].waitForExistence(timeout: 10))
        app.textFields["행동 결과 입력"].tap()
        app.textFields["행동 결과 입력"].typeText("수정 전 진행 메모")
        startLocalGoal(app, goal: retained, firstAction: firstAction)
        app.textFields["행동 결과 입력"].tap()
        app.textFields["행동 결과 입력"].typeText("남길 목표의 메모")
        selectLocalGoal(app, goal: original)
        app.buttons["목표 보기"].tap()
        app.buttons["문구 수정"].tap()
        let statement = app.textFields["목표 문구"]
        statement.tap()
        statement.typeText("(수정)")
        let edited = try XCTUnwrap(statement.value as? String)
        XCTAssertNotEqual(edited, original)
        XCTAssertTrue(edited.contains("(수정)"))
        app.buttons["문구 저장"].tap()
        XCTAssertTrue(app.staticTexts[edited].waitForExistence(timeout: 10))
        app.buttons["닫기"].tap()
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts[nextAction].waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, "수정 전 진행 메모")
        app.buttons["목표 보기"].tap()
        XCTAssertTrue(app.staticTexts[edited].waitForExistence(timeout: 10))
        app.buttons["목표 삭제"].tap()
        let confirmation = app.alerts["목표를 삭제할까요?"]
        XCTAssertTrue(confirmation.waitForExistence(timeout: 10))
        confirmation.buttons["취소"].tap()
        XCTAssertTrue(app.buttons["문구 수정"].waitForExistence(timeout: 10))
        XCTAssertNotNil(attach(app, name: "local-core-delete-cancelled"))
        app.buttons["목표 중단"].tap()
        XCTAssertTrue(app.staticTexts["진행 상태와 입력·기록을 보관했어요."].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["수정 전 진행 메모"].exists)
        XCTAssertNotNil(attach(app, name: "local-core-stopped-records"))
        app.buttons["목표 목록"].tap()
        let editedEntry = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", edited + ","))
        XCTAssertTrue(editedEntry.firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(editedEntry.firstMatch.label.contains("목표 중단"))
        XCTAssertTrue(editedEntry.firstMatch.label.contains("완료한 행동 1개"))
        app.buttons["닫기"].tap()
        app.buttons["목표 보기"].tap()
        app.buttons["목표 삭제"].tap()
        XCTAssertTrue(confirmation.waitForExistence(timeout: 10))
        confirmation.buttons["삭제"].tap()
        app.buttons["목표 목록"].tap()
        XCTAssertEqual(editedEntry.count, 0)
        let retainedEntry = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", retained + ",")).firstMatch
        XCTAssertTrue(retainedEntry.waitForExistence(timeout: 10))
        retainedEntry.tap()
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts[firstAction].waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields["행동 결과 입력"].value as? String, "남길 목표의 메모")
        XCTAssertNotNil(attach(app, name: "local-core-retained-after-delete"))
        app.buttons["목표 목록"].tap()
        XCTAssertEqual(editedEntry.count, 0)
    }

    func testActualMockScreensWithTimingOnAndOff() throws {
        continueAfterFailure = false
        let url = try XCTUnwrap(ProcessInfo.processInfo.environment["SMALLNEXT_TIMING_TEST_URL"])
        let app = XCUIApplication()
        app.launchArguments = ["-ios_core_flow", "YES", "-development_ai_url", url, "-suggestion_timing", "NO"]
        app.launch()
        // 매 실행 새 목표를 사용한다. 기존 목표와 완료 기록은 지우지 않는다.
        newGoal(app)
        app.textFields["목표 한 문장"].tap()
        app.textFields["목표 한 문장"].typeText("모의 책상 정리")
        app.buttons["목표 정리"].tap()
        XCTAssertTrue(app.buttons["확인하고 시작"].waitForExistence(timeout: 10))
        XCTAssertEqual(markers(app).count, 0)
        attach(app, name: "OFF-goal-summary")
        app.terminate()
        app.launchArguments = ["-ios_core_flow", "YES", "-development_ai_url", url, "-suggestion_timing", "YES"]
        app.launch()
        observe(app, button: "확인하고 시작", kind: "first_action", outcome: "action")
        observe(app, button: "더 작게", kind: "smaller", outcome: "action")
        observe(app, button: "더 작게", kind: "smaller", outcome: "question")
        observe(app, button: "완료", kind: "next_action", outcome: "failed")
        XCTAssertTrue(app.staticTexts["행동을 준비하지 못했어요."].exists)
    }

    func testDelayedNormalMockScreen() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["SMALLNEXT_TIMING_DELAYED_TEST"] == "1",
                          "별도로 지정한 35초 모의 사례만 1회 실행한다.")
        continueAfterFailure = false
        let url = try XCTUnwrap(ProcessInfo.processInfo.environment["SMALLNEXT_TIMING_TEST_URL"])
        let app = XCUIApplication()
        app.launchArguments = ["-ios_core_flow", "YES", "-development_ai_url", url, "-suggestion_timing", "NO"]
        app.launch()
        newGoal(app)
        app.textFields["목표 한 문장"].tap()
        app.textFields["목표 한 문장"].typeText("35초 모의 펜 정리")
        app.buttons["목표 정리"].tap()
        XCTAssertTrue(app.buttons["확인하고 시작"].waitForExistence(timeout: 10))
        app.terminate()
        app.launchArguments = ["-ios_core_flow", "YES", "-development_ai_url", url, "-suggestion_timing", "YES"]
        app.launch()
        observe(app, button: "확인하고 시작", kind: "first_action", outcome: "action",
                budget: 60, expectedAction: "펜 다섯 개 정리하기")
    }

    func testFirstInsufficientInfoRestoresAndReturnsToGoalList() throws {
        continueAfterFailure = false
        let url = try XCTUnwrap(ProcessInfo.processInfo.environment["SMALLNEXT_TIMING_TEST_URL"])
        let app = XCUIApplication()
        app.launchArguments = ["-ios_core_flow", "YES", "-user_server_ai", "NO", "-development_ai_url", url, "-suggestion_timing", "NO"]
        app.launch()
        newGoal(app)
        let goal = "정보 부족 안내 검증 \(UUID().uuidString)"
        app.textFields["목표 한 문장"].tap()
        app.textFields["목표 한 문장"].typeText(goal)
        app.buttons["목표 정리"].tap()
        XCTAssertTrue(app.buttons["확인하고 시작"].waitForExistence(timeout: 10))
        app.buttons["확인하고 시작"].tap()
        let title = "지금은 새 행동을 제안하기 어려워요"
        let reason = "현재 제공된 정보로는 **당시 역할**을 확인할 수 없어요."
        XCTAssertTrue(app.staticTexts[title].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts[reason].exists)
        XCTAssertTrue(app.buttons["돌아가기"].isHittable)
        XCTAssertFalse(app.buttons["완료"].exists)
        XCTAssertFalse(app.buttons["다시 시도"].exists)
        XCTAssertTrue(app.buttons["새 정보 추가"].isHittable)
        XCTAssertNotNil(attach(app, name: "first-insufficient-info"))
        let tree = XCTAttachment(string: app.debugDescription)
        tree.name = "first-insufficient-info-accessibility-tree"
        tree.lifetime = .keepAlways
        add(tree)
        XCTAssertLessThan(app.staticTexts[title].frame.maxY, app.staticTexts[reason].frame.minY)
        XCTAssertLessThan(app.staticTexts[reason].frame.maxY, app.buttons["돌아가기"].frame.minY)
        app.buttons["돌아가기"].tap()
        let entry = goalEntry(app, goal: goal)
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        XCTAssertTrue(entry.label.contains("완료한 행동 0개"))
        entry.tap()
        XCTAssertTrue(app.staticTexts[title].waitForExistence(timeout: 10))
        app.buttons["새 정보 추가"].tap()
        let editor = app.textFields["추가로 알려줄 내용"]
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        editor.typeText("제가 첫 문단을 작성했어요.")
        app.terminate()
        app.launch()
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        XCTAssertEqual(editor.value as? String, "제가 첫 문단을 작성했어요.")
        app.swipeUp()
        app.buttons["확인하고 저장"].tap()
        XCTAssertTrue(app.staticTexts["보충 내용을 저장했어요."].waitForExistence(timeout: 5))
        let previousNotice = "이 안내 이후 새 정보를 저장했어요. 아직 다시 제안받지 않았어요."
        XCTAssertTrue(app.staticTexts[previousNotice].exists)
        XCTAssertTrue(app.buttons["새 정보로 다시 제안"].exists)
        XCTAssertNotNil(attach(app, name: "supplemental-confirmed-with-previous-notice"))
        let savedTree = XCTAttachment(string: app.debugDescription)
        savedTree.name = "supplemental-saved-accessibility-tree"
        savedTree.lifetime = .keepAlways
        add(savedTree)
        app.terminate()
        app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        app.launch()
        XCTAssertTrue(app.staticTexts[title].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts[reason].exists)
        XCTAssertTrue(app.staticTexts[previousNotice].exists)
        app.buttons["새 정보 추가"].tap()
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        XCTAssertEqual(editor.value as? String, "제가 첫 문단을 작성했어요.")
        editor.typeText(" 수정 중")
        XCTAssertNotNil(attach(app, name: "first-insufficient-info-large-text-restored"))
        app.swipeUp()
        app.buttons["돌아가기"].tap()
        let restoredEntry = goalEntry(app, goal: goal)
        XCTAssertTrue(restoredEntry.waitForExistence(timeout: 10))
        restoredEntry.tap()
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        XCTAssertEqual(editor.value as? String, "제가 첫 문단을 작성했어요. 수정 중")
    }

    func testConfirmedSupplementalFirstActionWaitsForExplicitRequestAndRestores() throws {
        continueAfterFailure = false
        let url = try XCTUnwrap(ProcessInfo.processInfo.environment["SMALLNEXT_TIMING_TEST_URL"])
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<4 { root.deleteLastPathComponent() }
        let shared = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("contracts/fixtures/insufficient-info.json"))) as! [String: Any]
        let scenario = shared["supplemental_first_action"] as! [String: Any]
        let confirmed = (scenario["confirmed_text"] as! String).replacingOccurrences(of: "\r\n", with: "\n")
        let app = XCUIApplication()
        app.launchArguments = ["-ios_core_flow", "YES", "-user_server_ai", "NO", "-development_ai_url", url, "-suggestion_timing", "NO"]
        app.launch()
        newGoal(app)
        app.textFields["목표 한 문장"].tap()
        app.textFields["목표 한 문장"].typeText("정보 부족 안내 검증 \(UUID().uuidString)")
        app.buttons["목표 정리"].tap()
        XCTAssertTrue(app.buttons["확인하고 시작"].waitForExistence(timeout: 10))
        app.buttons["확인하고 시작"].tap()
        let title = "지금은 새 행동을 제안하기 어려워요"
        XCTAssertTrue(app.staticTexts[title].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["새 정보로 다시 제안"].exists)
        app.buttons["새 정보 추가"].tap()
        let editor = app.textFields["추가로 알려줄 내용"]
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        editor.typeText(confirmed)
        app.swipeUp()
        app.buttons["확인하고 저장"].tap()
        XCTAssertTrue(app.buttons["새 정보로 다시 제안"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts[title].exists)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["새 정보로 다시 제안"].waitForExistence(timeout: 10))
        XCTAssertNotNil(attach(app, name: "confirmed-supplemental-awaiting-explicit-request"))
        if !app.buttons["새 정보로 다시 제안"].isHittable { app.swipeUp() }
        app.buttons["새 정보로 다시 제안"].tap()
        let response = scenario["response"] as! [String: Any]
        let task = (response["proposal"] as! [String: Any])["action"] as! String
        XCTAssertTrue(app.staticTexts[task].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["완료"].exists)
        XCTAssertFalse(app.buttons["새 정보로 다시 제안"].exists)
        XCTAssertNotNil(attach(app, name: "supplemental-first-action"))
        let tree = XCTAttachment(string: app.debugDescription)
        tree.name = "supplemental-first-action-accessibility-tree"
        tree.lifetime = .keepAlways
        add(tree)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts[task].waitForExistence(timeout: 10))
    }

    func testActionQuestionsRestoreAndRetryOriginalKindWithNewInformation() throws {
        continueAfterFailure = false
        let url = try XCTUnwrap(ProcessInfo.processInfo.environment["SMALLNEXT_TIMING_TEST_URL"])
        let question = "직접 확인할 수 있는 기록이 있나요?"
        let title = "지금은 새 행동을 제안하기 어려워요"
        for kind in ["first_action", "smaller", "next_action", "replacement"] {
            let app = XCUIApplication()
            app.launchArguments = ["-ios_core_flow", "YES", "-user_server_ai", "NO", "-development_ai_url", url, "-suggestion_timing", "NO"]
            app.launch()
            newGoal(app)
            let goal = "후속 질문 검증 \(kind) \(UUID().uuidString)"
            app.textFields["목표 한 문장"].tap()
            app.textFields["목표 한 문장"].typeText(goal)
            app.buttons["목표 정리"].tap()
            XCTAssertTrue(app.buttons["확인하고 시작"].waitForExistence(timeout: 10))
            app.buttons["확인하고 시작"].tap()
            if kind != "first_action" {
                XCTAssertTrue(app.staticTexts["펜 다섯 개 정리하기"].waitForExistence(timeout: 10))
                if kind == "replacement" {
                    app.buttons["더 보기"].tap()
                    app.buttons["나중에"].tap()
                } else { app.buttons[kind == "smaller" ? "더 작게" : "완료"].tap() }
            }
            let field = app.textFields[question]
            XCTAssertTrue(field.waitForExistence(timeout: 10))
            if !field.isHittable { app.swipeUp() }
            field.tap()
            field.typeText("모르고 확인할 자료도 없어요.")
            app.terminate()
            app.launch()
            XCTAssertTrue(field.waitForExistence(timeout: 10))
            XCTAssertEqual(field.value as? String, "모르고 확인할 자료도 없어요.")
            if !field.isHittable { app.swipeUp() }
            XCTAssertNotNil(attach(app, name: "\(kind)-question-restored"))
            if !app.buttons["답하기"].isHittable { app.swipeUp() }
            app.buttons["답하기"].tap()
            XCTAssertTrue(app.staticTexts[title].waitForExistence(timeout: 10))
            XCTAssertFalse(app.buttons["다시 시도"].exists)
            XCTAssertFalse(app.buttons["완료"].exists)
            XCTAssertNotNil(attach(app, name: "\(kind)-information-notice"))
            let tree = XCTAttachment(string: app.debugDescription)
            tree.name = "\(kind)-question-notice-accessibility-tree"
            tree.lifetime = .keepAlways
            add(tree)
            app.buttons["돌아가기"].tap()
            if kind == "smaller" {
                XCTAssertTrue(app.staticTexts["펜 다섯 개 정리하기"].waitForExistence(timeout: 10))
                XCTAssertTrue(app.buttons["완료"].exists)
                app.buttons["목표 목록"].tap()
            }
            let entry = goalEntry(app, goal: goal)
            XCTAssertTrue(entry.waitForExistence(timeout: 10))
            XCTAssertTrue(entry.label.contains("완료한 행동 \(kind == "next_action" ? 1 : 0)개"))
            entry.tap()
            XCTAssertTrue(app.staticTexts[title].waitForExistence(timeout: 5))
            app.buttons["새 정보 추가"].tap()
            let supplemental = app.textFields["추가로 알려줄 내용"]
            XCTAssertTrue(supplemental.waitForExistence(timeout: 5))
            supplemental.tap()
            supplemental.typeText("제가 첫 문단을 작성했어요.")
            if !app.buttons["확인하고 저장"].isHittable { app.swipeUp() }
            app.buttons["확인하고 저장"].tap()
            XCTAssertTrue(app.staticTexts["이 안내 이후 새 정보를 저장했어요. 아직 다시 제안받지 않았어요."].waitForExistence(timeout: 5))
            app.terminate()
            app.launch()
            let retry = app.buttons["새 정보로 다시 제안"]
            XCTAssertTrue(retry.waitForExistence(timeout: 10))
            XCTAssertTrue(retry.label.contains("새 정보로 다시 제안"))
            if !retry.isHittable { app.swipeUp() }
            XCTAssertNotNil(attach(app, name: "\(kind)-supplemental-restored"))
            retry.tap()
            let action = "확인한 첫 문단을 메모에 옮기기"
            XCTAssertTrue(app.staticTexts[action].waitForExistence(timeout: 10))
            XCTAssertTrue(app.buttons["완료"].exists)
            XCTAssertFalse(retry.exists)
            XCTAssertNotNil(attach(app, name: "\(kind)-supplemental-action"))
            let retryTree = XCTAttachment(string: app.debugDescription)
            retryTree.name = "\(kind)-supplemental-accessibility-tree"
            retryTree.lifetime = .keepAlways
            add(retryTree)
            app.terminate()
            app.launch()
            XCTAssertTrue(app.staticTexts[action].waitForExistence(timeout: 10))
            app.buttons["목표 목록"].tap()
            let completed = goalEntry(app, goal: goal)
            XCTAssertTrue(completed.waitForExistence(timeout: 10))
            XCTAssertTrue(completed.label.contains("완료한 행동 \(kind == "next_action" ? 1 : 0)개"))
            app.terminate()
        }
    }

    func testObservationRejectsMissingScreenshotAndLateCapture() {
        XCTAssertEqual(termination(elapsed: 59, budget: 60, screenshotHash: nil), "missing")
        XCTAssertEqual(termination(elapsed: 60.1, budget: 60, screenshotHash: "hash"), "time_exceeded")
        XCTAssertEqual(termination(elapsed: 59, budget: 60, screenshotHash: "hash"), "observed")
    }

    private func localApp() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-ios_core_flow", "YES", "-user_server_ai", "NO", "-suggestion_timing", "NO"]
        app.launch()
        XCTAssertTrue(app.buttons["목표 목록"].waitForExistence(timeout: 10))
        return app
    }
    private func startLocalGoal(_ app: XCUIApplication, goal: String, firstAction: String) {
        newGoal(app)
        app.textFields["목표 한 문장"].tap()
        app.textFields["목표 한 문장"].typeText(goal)
        app.buttons["목표 정리"].tap()
        XCTAssertTrue(app.buttons["확인하고 시작"].waitForExistence(timeout: 10))
        app.buttons["확인하고 시작"].tap()
        XCTAssertTrue(app.staticTexts[firstAction].waitForExistence(timeout: 10))
        XCTAssertNotNil(attach(app, name: "local-core-\(goal)"))
    }
    private func selectLocalGoal(_ app: XCUIApplication, goal: String) {
        app.buttons["목표 목록"].tap()
        let entry = goalEntry(app, goal: goal)
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
    }
    private func goalEntry(_ app: XCUIApplication, goal: String) -> XCUIElement {
        let entry = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", goal + ",")).firstMatch
        for _ in 0..<20 {
            if entry.exists && entry.isHittable { break }
            app.swipeUp()
        }
        return entry
    }
    private func newGoal(_ app: XCUIApplication) {
        if !app.textFields["목표 한 문장"].exists {
            app.buttons["목표 목록"].tap()
            app.buttons["새 목표"].tap()
        }
    }
    private func markers(_ app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "timing:"))
    }
    private func observe(_ app: XCUIApplication, button: String, kind: String, outcome: String,
                         budget: Double = 10, expectedAction: String? = nil) {
        let previous = markers(app).firstMatch.exists ? markers(app).firstMatch.identifier : ""
        let clock = ContinuousClock()
        let started = clock.now
        var last = started
        var maxInterval = 0.0
        app.buttons[button].tap()
        var observed: String?
        var screenshotHash: String?
        var stabilization = 0.0
        var unstableSamples = 0
        while seconds(started.duration(to: clock.now)) < budget {
            let marker = markers(app).firstMatch
            if marker.exists, marker.isHittable {
                let id = marker.identifier
                if id != previous, id.hasSuffix(":\(kind):\(outcome)") { observed = id }
            }
            if let id = observed {
                // 전환 중 접근성 표식도 먼저 생긴다. 사진을 확인할 상한에 안정화 대기를 포함한다.
                let stabilizationStart = clock.now
                Thread.sleep(forTimeInterval: 0.5)
                let stable = marker.exists && marker.isHittable && marker.identifier == id
                let expectedVisible = expectedAction.map { app.staticTexts[$0].exists && app.staticTexts[$0].isHittable } ?? true
                stabilization = seconds(stabilizationStart.duration(to: clock.now))
                if stable && expectedVisible && seconds(started.duration(to: clock.now)) < budget {
                    screenshotHash = attach(app, name: "\(kind)-\(outcome)-\(id)")
                } else {
                    unstableSamples += 1
                    observed = nil
                }
            }
            let now = clock.now
            maxInterval = max(maxInterval, seconds(last.duration(to: now)))
            last = now
            if screenshotHash != nil { break }
            Thread.sleep(forTimeInterval: 0.1)
        }
        // UI 조회나 사진 처리 자체가 budget을 넘을 수 있다. 늦은 사진도 성공으로 바꾸지 않는다.
        let ended = clock.now
        maxInterval = max(maxInterval, seconds(last.duration(to: ended)))
        let elapsed = seconds(started.duration(to: ended))
        let status = termination(elapsed: elapsed, budget: budget, screenshotHash: screenshotHash)
        let parts = observed?.split(separator: ":")
        let report: [String: Any] = [
            "run_id": parts.map { String($0[1]) } as Any? ?? NSNull(),
            "request_kind": kind, "expected_outcome": outcome,
            "expected_action": expectedAction as Any? ?? NSNull(),
            "observed_upper_seconds": elapsed, "budget_seconds": budget,
            "max_sample_interval_seconds": maxInterval,
            "stabilization_requested_seconds": 0.5, "stabilization_actual_seconds": stabilization,
            "unstable_samples": unstableSamples, "missing_screenshot": screenshotHash == nil,
            "evidence_sha256": screenshotHash as Any? ?? NSNull(), "termination": status,
            "method": "XCTest-visible-accessibility+result-screenshot; manual pixel verification required",
            "mock_only": true
        ]
        let data = try! JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "observation-\(kind)-\(outcome)"
        attachment.lifetime = .keepAlways
        add(attachment)
        XCTAssertEqual(status, "observed")
        XCTAssertNotNil(observed)
    }

    private func termination(elapsed: Double, budget: Double, screenshotHash: String?) -> String {
        if elapsed > budget { return "time_exceeded" }
        return screenshotHash == nil ? "missing" : "observed"
    }
    private func seconds(_ duration: Duration) -> Double {
        Double(duration.components.seconds) + Double(duration.components.attoseconds) / 1e18
    }
    @discardableResult
    private func attach(_ app: XCUIApplication, name: String) -> String? {
        let png = app.screenshot().pngRepresentation
        guard !png.isEmpty else { return nil }
        let attachment = XCTAttachment(data: png, uniformTypeIdentifier: "public.png")
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        return SHA256.hash(data: png).map { String(format: "%02x", $0) }.joined()
    }
}

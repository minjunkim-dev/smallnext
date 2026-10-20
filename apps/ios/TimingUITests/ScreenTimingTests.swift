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
        let entry = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", goal + ",")).firstMatch
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
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

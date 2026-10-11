import XCTest

/// 별도 TimingValidation scheme에서 모의 Rust 서버와 실행한다.
@MainActor
final class ScreenTimingTests: XCTestCase {
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

    private func newGoal(_ app: XCUIApplication) {
        if !app.textFields["목표 한 문장"].exists {
            app.buttons["목표 목록"].tap()
            app.buttons["새 목표"].tap()
        }
    }
    private func markers(_ app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "timing:"))
    }
    private func observe(_ app: XCUIApplication, button: String, kind: String, outcome: String) {
        let previous = markers(app).firstMatch.exists ? markers(app).firstMatch.identifier : ""
        let clock = ContinuousClock()
        let started = clock.now
        var last = started
        var maxInterval = 0.0
        app.buttons[button].tap()
        var observed: String?
        while seconds(started.duration(to: clock.now)) < 10 {
            let marker = markers(app).firstMatch
            if marker.exists, marker.isHittable {
                let id = marker.identifier
                if id != previous, id.hasSuffix(":\(kind):\(outcome)") { observed = id }
            }
            if let id = observed {
                // 전환 중 접근성 표식도 먼저 생긴다. 사진을 확인할 상한에 안정화 대기를 포함한다.
                Thread.sleep(forTimeInterval: 0.5)
                if marker.exists, marker.isHittable, marker.identifier == id { attach(app, name: "\(kind)-\(outcome)") }
                else { observed = nil }
            }
            let now = clock.now
            maxInterval = max(maxInterval, seconds(last.duration(to: now)))
            last = now
            if observed != nil { break }
            Thread.sleep(forTimeInterval: 0.1)
        }
        XCTAssertNotNil(observed)
        let report = "\(observed ?? "missing") button-before-tap-to-first-result-screenshot-upper-bound-ms=\(seconds(started.duration(to: last)) * 1000) max-sample-interval-ms=\(maxInterval * 1000) stabilization-ms=500 method=XCTest-visible-accessibility+screenshot mock-only=true"
        let attachment = XCTAttachment(string: report)
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    private func seconds(_ duration: Duration) -> Double {
        Double(duration.components.seconds) + Double(duration.components.attoseconds) / 1e18
    }
    private func attach(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}

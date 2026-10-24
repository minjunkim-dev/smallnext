#if DEBUG
import Foundation
import XCTest
@testable import SmallnextCore

@MainActor
final class DevelopmentAITests: XCTestCase {
    private func provider() -> any ActionSuggestionProvider {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [DevelopmentTransport.self]
        return HTTPActionSuggestionProvider.development(baseURL: URL(string: "http://127.0.0.1:8080")!,
                                                        token: "test-token", session: URLSession(configuration: config))
    }

    private nonisolated static func accepted(_ request: URLRequest, status: String = "action", complete: Bool = false) throws -> Data {
        let payload = try JSONSerialization.jsonObject(with: request.httpBody!) as! [String: Any]
        let input = payload["input"] as! [String: Any]
        return try JSONSerialization.data(withJSONObject: ["disposition": "accepted", "proposal": [
            "status": status, "action": "펜 하나 옮기기", "completion_condition": "펜이 펜꽂이에 있다", "estimated_minutes": 1,
            "reason": "물건 하나를 정리한다", "remaining_work": input["remaining_work"]!,
            "preserved_completed_ids": input["completed_ids"]!, "goal_completed": complete, "current_action_completed": complete,
        ]])
    }

    func testHTTPProposalPreservesSplitScopeCompletedIDsAndCompletionFlags() async throws {
        let provider = provider()
        DevelopmentTransport.store.reset()
        DevelopmentTransport.store.handler = { request in (200, try Self.accepted(request, complete: true)) }
        var request = SuggestionRequest(kind: .smaller, goal: "책상 정리", currentAction: ProposedAction(task: "펜 정리", doneWhen: "정리됨", estimatedMinutes: 5), completedTasks: ["종이 정리"])
        request.stateKey = "1:2"
        request.remainingTasks = ["책상 왼쪽 정리", "펜 정리"]
        request.completedActionIDs = ["7"]
        request.splitSources = ["책상 왼쪽 정리"]
        request.blocker = "무엇부터 할지 모른다"
        let candidate = try await provider.suggest(request)
        guard case .action(let action) = candidate else { return XCTFail("\(candidate)") }
        XCTAssertTrue(action.marksGoalComplete)
        XCTAssertTrue(action.marksCurrentActionComplete)
        let sent = DevelopmentTransport.store.requests
        XCTAssertEqual(sent.count, 1)
        XCTAssertEqual(sent.first?.value(forHTTPHeaderField: "Authorization"), "Bearer test-token")
        let payload = try JSONSerialization.jsonObject(with: sent[0].httpBody!) as! [String: Any]
        let input = payload["input"] as! [String: Any]
        XCTAssertEqual(input["remaining_work"] as? [String], ["책상 정리", "책상 왼쪽 정리", "펜 정리"])
        XCTAssertEqual(input["completed_ids"] as? [String], ["7"])
        XCTAssertEqual(input["current_blocker"] as? String, request.blocker)
        let previous = input["previous_proposals"] as! [[String: Any]]
        XCTAssertEqual(previous.map { $0["action"] as! String }, ["책상 왼쪽 정리", "펜 정리"])
    }

    func testTransportFailuresMapWithoutAutomaticRetry() async throws {
        let provider = provider()
        let request = SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: [], stateKey: "1:0")
        for (code, expected) in [(URLError.Code.networkConnectionLost, SuggestionFailure.connectionLost), (.timedOut, .timedOut)] {
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { _ in throw URLError(code) }
            do { _ = try await provider.suggest(request); XCTFail("must fail") }
            catch { XCTAssertEqual(error as? SuggestionFailure, expected) }
            XCTAssertEqual(DevelopmentTransport.store.requests.count, 1)
        }
        for (value, expected) in [("rejected", SuggestionFailure.rejected), ("uncertain", .undecidable), ("budget_limit", .budgetLimit), ("timed_out", .timedOut)] {
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { _ in (200, Data("{\"disposition\":\"\(value)\"}".utf8)) }
            do { _ = try await provider.suggest(request); XCTFail("must fail") }
            catch { XCTAssertEqual(error as? SuggestionFailure, expected) }
            XCTAssertEqual(DevelopmentTransport.store.requests.count, 1)
        }
    }

    func testCancellationStopsHTTPTransport() async throws {
        let provider = provider()
        DevelopmentTransport.store.reset()
        DevelopmentTransport.store.handler = nil
        let task = Task { try await provider.suggest(SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: [], stateKey: "1:0")) }
        for _ in 0..<200 where DevelopmentTransport.store.requests.isEmpty { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertEqual(DevelopmentTransport.store.requests.count, 1)
        task.cancel()
        do { _ = try await task.value; XCTFail("must cancel") }
        catch { XCTAssertTrue(error is CancellationError) }
        for _ in 0..<200 where !DevelopmentTransport.store.stopped { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(DevelopmentTransport.store.stopped)
    }

    func testGoalSummaryQuestionAndNoAlternativeKeepTheirCandidateTypes() async throws {
        let provider = provider()
        for (kind, status, expected) in [
            (SuggestionKind.goalPreparation, "goal_summary", SuggestionCandidate.goalSummary("펜이 펜꽂이에 있다")),
            (.goalPreparation, "need_info", .question("펜 하나 옮기기")),
            (.replacement, "no_action", .noAction),
        ] {
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { request in (200, try Self.accepted(request, status: status)) }
            let candidate = try await provider.suggest(SuggestionRequest(kind: kind, goal: "펜 정리", currentAction: nil, completedTasks: [], stateKey: "1:0"))
            XCTAssertEqual(candidate, expected)
        }
    }

    func testSharedInsufficientInfoIsAValidTransportResponse() async throws {
        let response = try InsufficientInfoFixture.response()
        DevelopmentTransport.store.reset()
        DevelopmentTransport.store.handler = { _ in (200, response) }
        for kind in [SuggestionKind.firstAction, .nextAction, .smaller, .replacement] {
            let request = SuggestionRequest(kind: kind, goal: "과거 경력 사실 정리", currentAction: nil, completedTasks: [])
            let candidate = try await provider().suggest(request)
            XCTAssertEqual(candidate, .insufficientInfo(try InsufficientInfoFixture.reason()))
            XCTAssertNotNil(CandidatePolicy.accept(candidate, for: request))
        }
        XCTAssertEqual(DevelopmentTransport.store.requests.count, 4)
    }

    func testInsufficientInfoRejectsMalformedFieldsAndGoalPreparation() async throws {
        let base = try JSONSerialization.jsonObject(with: InsufficientInfoFixture.response()) as! [String: Any]
        for (field, value) in [("action", "가짜 행동" as Any), ("completion_condition", " " as Any),
                               ("estimated_minutes", 1), ("reason", " "), ("goal_completed", true),
                               ("current_action_completed", true), ("preserved_completed_ids", ["new"]),
                               ("remaining_work", ["changed"]), ("status", "future_status")] {
            var response = base
            var proposal = response["proposal"] as! [String: Any]
            proposal[field] = value
            response["proposal"] = proposal
            let bytes = try JSONSerialization.data(withJSONObject: response)
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { _ in (200, bytes) }
            do {
                _ = try await provider().suggest(SuggestionRequest(kind: .firstAction, goal: "과거 경력 사실 정리", currentAction: nil, completedTasks: []))
                XCTFail("must reject \(field)")
            } catch { XCTAssertEqual(error as? SuggestionFailure, .rejected, field) }
            XCTAssertEqual(DevelopmentTransport.store.requests.count, 1)
        }
        let bytes = try InsufficientInfoFixture.response()
        DevelopmentTransport.store.handler = { _ in (200, bytes) }
        do {
            _ = try await provider().suggest(SuggestionRequest(kind: .goalPreparation, goal: "과거 경력 사실 정리", currentAction: nil, completedTasks: []))
            XCTFail("goal preparation cannot apply this notice")
        } catch { XCTAssertEqual(error as? SuggestionFailure, .rejected) }
    }

    func testFingerprintNormalizesOnlyActualInputAndPreservesOrder() throws {
        var request = SuggestionRequest(kind: .smaller, goal: "  정리\r\n계속  ", currentAction: ProposedAction(task: "한 부분", doneWhen: "결과", estimatedMinutes: 2), completedTasks: ["하나", "둘"], stateKey: "1:2")
        request.remainingTasks = ["첫째", "둘째"]
        request.completedActionIDs = ["7", "3"]
        let original = request
        let fingerprint = try HTTPActionSuggestionProvider.inputFingerprint(request)
        XCTAssertEqual(fingerprint.count, 64)
        request.goal = "정리\n계속"
        request.stateKey = "different-goal:999"
        XCTAssertEqual(try HTTPActionSuggestionProvider.inputFingerprint(request), fingerprint)
        XCTAssertEqual(original.goal, "  정리\r\n계속  ")
        request.remainingTasks.reverse()
        XCTAssertNotEqual(try HTTPActionSuggestionProvider.inputFingerprint(request), fingerprint)
        request = original
        request.completedActionIDs.reverse()
        XCTAssertNotEqual(try HTTPActionSuggestionProvider.inputFingerprint(request), fingerprint)
        request = original
        request.kind = .firstAction
        XCTAssertNotEqual(try HTTPActionSuggestionProvider.inputFingerprint(request), fingerprint)
        request = original
        request.context.answers = [GoalAnswer(question: "어디", answer: "모름")]
        XCTAssertNotEqual(try HTTPActionSuggestionProvider.inputFingerprint(request), fingerprint)
        request = original
        request.context.materialExcerpt = "사용자가 선택한 원문"
        XCTAssertNotEqual(try HTTPActionSuggestionProvider.inputFingerprint(request), fingerprint)
        request = original
        request.currentAction?.doneWhen = "다른 결과"
        XCTAssertNotEqual(try HTTPActionSuggestionProvider.inputFingerprint(request), fingerprint)
    }

    func testOversizedBlockerIsNotTransmitted() async throws {
        DevelopmentTransport.store.reset()
        let provider = provider()
        let request = SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: [], blocker: String(repeating: "가", count: 683), stateKey: "1:0")
        do { _ = try await provider.suggest(request); XCTFail("must reject") }
        catch { XCTAssertEqual(error as? SuggestionFailure, .rejected) }
        XCTAssertTrue(DevelopmentTransport.store.requests.isEmpty)
    }

    func testTimingLinksTransportWithServerAndKeepsMissingTimeUnknown() async throws {
        let provider = provider()
        let request = SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: [], stateKey: "1:0")
        DevelopmentTransport.store.reset()
        DevelopmentTransport.store.handler = { request in (200, try Self.accepted(request)) }
        _ = try await provider.suggest(request)
        XCTAssertNil(DevelopmentTransport.store.requests[0].value(forHTTPHeaderField: "X-Smallnext-Timing"))
        let timing = SuggestionTiming(kind: .firstAction, start: SuggestionTiming.now)
        DevelopmentTransport.store.reset()
        DevelopmentTransport.store.handler = { request in
            var data = try JSONSerialization.jsonObject(with: Self.accepted(request)) as! [String: Any]
            data["_timing"] = ["run_id": timing.id, "generate_ms": 0.01, "check_ms": 0.01, "total_ms": 0.02]
            return (200, try JSONSerialization.data(withJSONObject: data))
        }
        _ = try await SuggestionTiming.$current.withValue(timing) { try await provider.suggest(request) }
        XCTAssertEqual(DevelopmentTransport.store.requests[0].value(forHTTPHeaderField: "X-Smallnext-Timing"), timing.id)
        let record = timing.snapshot()
        XCTAssertEqual(record.authApplicable, false)
        XCTAssertNil(record.authMS)
        XCTAssertNotNil(record.httpMS)
        XCTAssertEqual(record.server?.run_id, timing.id)
        XCTAssertNotNil(record.transportQueueResidualMS)
        XCTAssertNil(record.screenUpperBoundMS)
        let wrong = SuggestionTiming(kind: .firstAction, start: SuggestionTiming.now)
        _ = try await SuggestionTiming.$current.withValue(wrong) { try await provider.suggest(request) }
        XCTAssertNil(wrong.snapshot().server)
    }
}

#endif

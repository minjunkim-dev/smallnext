#if DEBUG
import Foundation
import XCTest
@testable import Smallnext

@MainActor
final class DevelopmentActionSuggestionProviderTests: XCTestCase {
    private func provider() -> DevelopmentActionSuggestionProvider {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [DevelopmentTransport.self]
        return DevelopmentActionSuggestionProvider(baseURL: URL(string: "http://127.0.0.1:8080")!,
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

    func testOversizedBlockerIsNotTransmitted() async throws {
        DevelopmentTransport.store.reset()
        let provider = provider()
        let request = SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: [], blocker: String(repeating: "가", count: 683), stateKey: "1:0")
        do { _ = try await provider.suggest(request); XCTFail("must reject") }
        catch { XCTAssertEqual(error as? SuggestionFailure, .rejected) }
        XCTAssertTrue(DevelopmentTransport.store.requests.isEmpty)
    }
}

final class DevelopmentTransport: URLProtocol, @unchecked Sendable {
    static let store = Store()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var request = request
        if request.httpBody == nil, let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }
                data.append(contentsOf: buffer.prefix(count))
            }
            request.httpBody = data
        }
        let handler = Self.store.record(request)
        guard let handler else { return }
        do {
            let (code, data) = try handler(request)
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() { Self.store.stop() }

    final class Store: @unchecked Sendable {
        typealias Handler = (URLRequest) throws -> (Int, Data)
        private let lock = NSLock()
        private var handlerValue: Handler?
        private var requestValues: [URLRequest] = []
        private var stoppedValue = false
        var handler: Handler? {
            get { lock.withLock { handlerValue } }
            set { lock.withLock { handlerValue = newValue } }
        }
        var requests: [URLRequest] { lock.withLock { requestValues } }
        var stopped: Bool { lock.withLock { stoppedValue } }
        func reset() { lock.withLock { handlerValue = nil; requestValues = []; stoppedValue = false } }
        func record(_ request: URLRequest) -> Handler? { lock.withLock { requestValues.append(request); return handlerValue } }
        func stop() { lock.withLock { stoppedValue = true } }
    }
}
#endif

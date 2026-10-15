import Foundation
import XCTest
@testable import SmallnextCore

// Server-path contract of HTTPActionSuggestionProvider; runs with swift test, no simulator.
@MainActor
final class ServerSuggestionProviderTests: XCTestCase {
    func testPlainHTTPOrCredentialURLNeverObtainsIdentity() async throws {
        for address in ["http://api.example.invalid", "https://name:pass@api.example.invalid", "https://api.example.invalid?token=x"] {
            let provider = HTTPActionSuggestionProvider.server(baseURL: URL(string: address)!, token: {
                XCTFail("invalid endpoint must not obtain identity")
                return "unused"
            })
            do { _ = try await provider.suggest(SuggestionRequest(kind:.firstAction, goal:"정리", currentAction:nil, completedTasks:[])); XCTFail("must reject") }
            catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
        }
    }

    #if DEBUG
    private func provider(token: @escaping @Sendable () async throws -> String = { "firebase-test-id-token" }) -> any ActionSuggestionProvider {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DevelopmentTransport.self]
        return HTTPActionSuggestionProvider.server(baseURL: URL(string:"https://api.example.invalid")!, token:token,
            session:URLSession(configuration:configuration))
    }

    private nonisolated static func accepted(_ request: URLRequest, status: String = "action", complete: Bool = false, wrongScope: Bool = false, blank: Bool = false) throws -> Data {
        let payload = try JSONSerialization.jsonObject(with:request.httpBody!) as! [String:Any]
        let input = payload["input"] as! [String:Any]
        return try JSONSerialization.data(withJSONObject:["disposition":"accepted","proposal":[
            "status":status,"action":"펜 하나 옮기기","completion_condition":blank ? " " : "펜이 펜꽂이에 있다","estimated_minutes":1,
            "reason":"한 물건만 옮긴다","remaining_work":wrongScope ? ["다른 범위"] : input["remaining_work"]!,
            "preserved_completed_ids":input["completed_ids"]!,"goal_completed":complete,"current_action_completed":complete]])
    }

    func testAuthTokenAndServerPathPreserveAllCandidateTypes() async throws {
        for (kind,status,expected) in [
            (SuggestionKind.firstAction,"action",SuggestionCandidate.action(ProposedAction(task:"펜 하나 옮기기",doneWhen:"펜이 펜꽂이에 있다",estimatedMinutes:1,marksGoalComplete:false))),
            (.smaller,"minimum",.minimalAction(ProposedAction(task:"펜 하나 옮기기",doneWhen:"펜이 펜꽂이에 있다",estimatedMinutes:1,marksGoalComplete:false))),
            (.goalPreparation,"need_info",.question("펜 하나 옮기기")),
            (.goalPreparation,"goal_summary",.goalSummary("펜이 펜꽂이에 있다")),
            (.replacement,"no_action",.noAction)
        ] {
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { request in (200,try Self.accepted(request,status:status)) }
            let candidate = try await provider().suggest(SuggestionRequest(kind:kind,goal:"책상 정리",currentAction:nil,completedTasks:[],stateKey:"2:3"))
            XCTAssertEqual(candidate,expected)
            XCTAssertEqual(DevelopmentTransport.store.requests.count,1)
            let sent = try XCTUnwrap(DevelopmentTransport.store.requests.first)
            XCTAssertEqual(sent.url?.path,"/v1/suggestions")
            XCTAssertEqual(sent.value(forHTTPHeaderField:"Authorization"),"Bearer firebase-test-id-token")
            XCTAssertEqual(sent.timeoutInterval,160)
        }
    }

    func testAuthenticationTransportAndServerFailuresNeverRetryAI() async throws {
        for (status,reason) in [(401,SuggestionFailure.rejected),(403,.rejected),(429,.budgetLimit),(504,.timedOut),(503,.failed),(409,.unavailable),(302,.failed)] {
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { _ in (status,Data()) }
            do { _ = try await provider().suggest(SuggestionRequest(kind:.firstAction,goal:"정리",currentAction:nil,completedTasks:[])); XCTFail("must fail") }
            catch { XCTAssertEqual(error as? SuggestionFailure,reason) }
            XCTAssertEqual(DevelopmentTransport.store.requests.count,1)
        }
        DevelopmentTransport.store.reset()
        do { _ = try await provider(token: { throw SuggestionFailure.unavailable }).suggest(SuggestionRequest(kind:.firstAction,goal:"정리",currentAction:nil,completedTasks:[])); XCTFail("must fail") }
        catch { XCTAssertEqual(error as? SuggestionFailure,.unavailable) }
        XCTAssertTrue(DevelopmentTransport.store.requests.isEmpty)
    }

    func testTimingSeparatesMockAuthenticationFromHTTPAndKeepsAuthFailureUnknown() async throws {
        DevelopmentTransport.store.reset()
        DevelopmentTransport.store.handler = { request in (200, try Self.accepted(request)) }
        let timing = SuggestionTiming(kind: .firstAction, start: SuggestionTiming.now)
        let delayed = provider(token: {
            try await Task.sleep(for: .milliseconds(20))
            return "mock-token"
        })
        let request = SuggestionRequest(kind: .firstAction, goal: "정리", currentAction: nil, completedTasks: [])
        _ = try await SuggestionTiming.$current.withValue(timing) { try await delayed.suggest(request) }
        XCTAssertEqual(timing.snapshot().authApplicable, true)
        XCTAssertGreaterThanOrEqual(try XCTUnwrap(timing.snapshot().authMS), 20)
        XCTAssertNotNil(timing.snapshot().httpMS)
        XCTAssertNil(timing.snapshot().server)
        let failed = SuggestionTiming(kind: .firstAction, start: SuggestionTiming.now)
        DevelopmentTransport.store.reset()
        do {
            _ = try await SuggestionTiming.$current.withValue(failed) {
                try await provider(token: { throw SuggestionFailure.rejected }).suggest(request)
            }
            XCTFail("must fail")
        } catch { XCTAssertEqual(error as? SuggestionFailure, .rejected) }
        XCTAssertNotNil(failed.snapshot().authMS)
        XCTAssertNil(failed.snapshot().httpMS)
        XCTAssertTrue(DevelopmentTransport.store.requests.isEmpty)
    }

    func testScopeMismatchBlankTextAndUnrepresentableCompletionClaimsCannotBecomeCandidates() async throws {
        let request = SuggestionRequest(kind:.goalPreparation,goal:"정리",currentAction:nil,completedTasks:[])
        for (status,complete,wrongScope,blank) in [("action",false,true,false),("need_info",true,false,false),("goal_summary",true,false,false),("no_action",false,false,true)] {
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { request in (200,try Self.accepted(request,status:status,complete:complete,wrongScope:wrongScope,blank:blank)) }
            do { _ = try await provider().suggest(request); XCTFail("must reject \(status)") }
            catch { XCTAssertEqual(error as? SuggestionFailure,.rejected) }
        }
    }

    func testActionCompletionClaimReachesCandidatePolicy() async throws {
        let request = SuggestionRequest(kind:.firstAction,goal:"정리",currentAction:nil,completedTasks:[])
        DevelopmentTransport.store.reset()
        DevelopmentTransport.store.handler = { request in (200,try Self.accepted(request,complete:true)) }
        let candidate = try await provider().suggest(request)
        guard case .action(let action) = candidate else { return XCTFail("\(candidate)") }
        XCTAssertTrue(action.marksGoalComplete)
        XCTAssertNil(CandidatePolicy.accept(candidate, for: request))
    }

    func testCancellationDuringIdentityPreparationNeverSendsAIRequest() async throws {
        DevelopmentTransport.store.reset()
        let client = provider(token: { try await Task.sleep(for:.seconds(10)); return "unused" })
        let pending = Task { try await client.suggest(SuggestionRequest(kind:.firstAction,goal:"정리",currentAction:nil,completedTasks:[])) }
        pending.cancel()
        do { _ = try await pending.value; XCTFail("must cancel") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertTrue(DevelopmentTransport.store.requests.isEmpty)
    }
    #endif
}

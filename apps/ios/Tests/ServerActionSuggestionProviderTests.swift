import Foundation
import XCTest
@testable import Smallnext

@MainActor
final class ServerActionSuggestionProviderTests: XCTestCase {
    func testAppBundleIncludesServerConfigurationKeys() {
        for key in ["SmallnextAPIBaseURL", "SmallnextFirebaseAppID", "SmallnextFirebaseSenderID",
                    "SmallnextFirebaseProjectID", "SmallnextFirebaseAPIKey"] {
            XCTAssertNotNil(Bundle.main.object(forInfoDictionaryKey: key) as? String, key)
        }
    }

    func testPlainHTTPOrCredentialURLNeverObtainsIdentity() async throws {
        for address in ["http://api.example.invalid", "https://name:pass@api.example.invalid", "https://api.example.invalid?token=x"] {
            let provider = ServerActionSuggestionProvider(baseURL: URL(string: address)!, token: {
                XCTFail("invalid endpoint must not obtain identity")
                return "unused"
            })
            do { _ = try await provider.suggest(SuggestionRequest(kind:.firstAction, goal:"정리", currentAction:nil, completedTasks:[])); XCTFail("must reject") }
            catch { XCTAssertEqual(error as? SuggestionFailure, .unavailable) }
        }
    }

    #if DEBUG
    private func provider(token: @escaping @Sendable () async throws -> String = { "firebase-test-id-token" }) -> ServerActionSuggestionProvider {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DevelopmentTransport.self]
        return ServerActionSuggestionProvider(baseURL: URL(string:"https://api.example.invalid")!, token:token,
            session:URLSession(configuration:configuration))
    }

    private nonisolated static func accepted(_ request: URLRequest, status: String = "action", complete: Bool = false, wrongScope: Bool = false) throws -> Data {
        let payload = try JSONSerialization.jsonObject(with:request.httpBody!) as! [String:Any]
        let input = payload["input"] as! [String:Any]
        return try JSONSerialization.data(withJSONObject:["disposition":"accepted","proposal":[
            "status":status,"action":"펜 하나 옮기기","completion_condition":"펜이 펜꽂이에 있다","estimated_minutes":1,
            "reason":"한 물건만 옮긴다","remaining_work":wrongScope ? ["다른 범위"] : input["remaining_work"]!,
            "preserved_completed_ids":input["completed_ids"]!,"goal_completed":complete,"current_action_completed":complete]])
    }

    func testFirebaseTokenAndServerPathPreserveAllCandidateTypes() async throws {
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

    func testCompletionClaimsAndScopeMismatchCannotBecomeCandidates() async throws {
        for (complete,wrongScope) in [(true,false),(false,true)] {
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { request in (200,try Self.accepted(request,complete:complete,wrongScope:wrongScope)) }
            do { _ = try await provider().suggest(SuggestionRequest(kind:.firstAction,goal:"정리",currentAction:nil,completedTasks:[])); XCTFail("must reject") }
            catch { XCTAssertEqual(error as? SuggestionFailure,.rejected) }
        }
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

    func testBundledUserServerFlagIsOff() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource:"feature-flags",withExtension:"json"))
        XCTAssertFalse(FeatureFlags.isEnabled("user_server_ai",registry:try Data(contentsOf:url)))
    }
    #endif
}

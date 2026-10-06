import XCTest
@testable import Smallnext

final class FeatureFlagsTests: XCTestCase {
    func testNilRegistryIsOff() {
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: nil))
    }

    func testBrokenJSONIsOff() {
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: Data()))
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: Data("{".utf8)))
    }

    func testMissingKeyIsOff() {
        let registry = json(#"{"version":1,"flags":[{"key":"other","default":true}]}"#)
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: registry))
    }

    func testDuplicateKeyIsOff() {
        let registry = json(
            """
            {"version":1,"flags":[
              {"key":"ios_core_flow","default":true},
              {"key":"ios_core_flow","default":false}
            ]}
            """
        )
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: registry))
    }

    func testNonBooleanDefaultIsOff() {
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: json(
            #"{"version":1,"flags":[{"key":"ios_core_flow","default":1}]}"#
        )))
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: json(
            #"{"version":1,"flags":[{"key":"ios_core_flow","default":"true"}]}"#
        )))
    }

    func testBooleanDefaults() {
        XCTAssertTrue(FeatureFlags.isEnabled("ios_core_flow", registry: json(
            #"{"version":1,"flags":[{"key":"ios_core_flow","default":true}]}"#
        )))
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: json(
            #"{"version":1,"flags":[{"key":"ios_core_flow","default":false}]}"#
        )))
    }

    func testWrongVersionIsOff() {
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: json(
            #"{"version":2,"flags":[{"key":"ios_core_flow","default":true}]}"#
        )))
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: json(
            #"{"flags":[{"key":"ios_core_flow","default":true}]}"#
        )))
    }

    func testBundledCoreFlowIsOff() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "feature-flags", withExtension: "json"))
        let data = try Data(contentsOf: url)
        XCTAssertFalse(FeatureFlags.isEnabled("ios_core_flow", registry: data))
    }

    #if DEBUG
    func testDebugProviderFirstCandidateAndExampleGoals() async throws {
        let goals = DebugActionSuggestionProvider.exampleGoals
        XCTAssertEqual(goals.filter { $0.contains("이력서") }.count, 1)
        XCTAssertGreaterThanOrEqual(goals.filter { !$0.contains("이력서") }.count, 3)

        let provider = DebugActionSuggestionProvider(delay: .zero)
        let candidate = try await provider.suggest(
            SuggestionRequest(kind: .firstAction, goal: goals[0], currentAction: nil, completedTasks: [])
        )
        guard case .action(let action) = candidate else {
            XCTFail("첫 후보는 행동이어야 한다")
            return
        }
        XCTAssertFalse(action.marksGoalComplete)
        XCTAssertGreaterThanOrEqual(action.estimatedMinutes, 2)
        XCTAssertLessThanOrEqual(action.estimatedMinutes, 15)

        let continued = try await provider.suggest(
            SuggestionRequest(
                kind: .nextAction,
                goal: goals[0],
                currentAction: nil,
                completedTasks: Array(repeating: "완료", count: 5)
            )
        )
        guard case .action(let next) = continued else {
            XCTFail("시퀀스 이후에도 행동을 반환해야 한다")
            return
        }
        XCTAssertEqual(next.task, "다음 한 가지 고르기 (5)")
    }
    #endif

    private func json(_ text: String) -> Data { Data(text.utf8) }
}

import Foundation
import XCTest
@testable import Smallnext

@MainActor
final class ProgressFlowTests: XCTestCase {
    private var directory: URL!
    private var path: String { directory.appendingPathComponent("flow.sqlite").path }

    private let first = ProposedAction(task: "관련 메모 하나 열기", doneWhen: "메모가 화면에 열려 있다", estimatedMinutes: 3)
    private let second = ProposedAction(task: "첫 문단 한 줄 쓰기", doneWhen: "문장 한 줄이 저장돼 있다", estimatedMinutes: 5)
    private let third = ProposedAction(task: "제목 한 줄 정하기", doneWhen: "제목이 적혀 있다", estimatedMinutes: 2)

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func makeFlow(_ provider: any ActionSuggestionProvider) throws -> ProgressFlow {
        try ProgressFlow(database: AppDatabase(path: path), provider: provider)
    }

    func testGoalToFirstActionToCompletionToNextActionSurvivesReopen() async throws {
        let provider = ScriptedProvider([.action(first), .action(second)])
        let secondCard: ActionCard
        do {
            let flow = try makeFlow(provider)
            XCTAssertEqual(flow.screen, .goalInput)

            try flow.createGoal("  주간 업무 보고서 초안 쓰기 ")
            XCTAssertEqual(flow.screen, .awaitingFirstAction)
            await flow.waitForSuggestion()
            guard case .currentAction(let firstCard) = flow.screen else { return XCTFail("\(flow.screen)") }
            XCTAssertEqual(firstCard.task, first.task)
            XCTAssertEqual(firstCard.doneWhen, first.doneWhen)
            XCTAssertEqual(firstCard.estimatedMinutes, first.estimatedMinutes)

            try flow.complete()
            try flow.complete()
            XCTAssertEqual(flow.screen, .awaitingNextAction)
            await flow.waitForSuggestion()
            guard case .currentAction(let card) = flow.screen else { return XCTFail("\(flow.screen)") }
            XCTAssertEqual(card.task, second.task)
            secondCard = card
        }

        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction, .nextAction])
        XCTAssertEqual(requests[0].goal, "주간 업무 보고서 초안 쓰기")
        XCTAssertEqual(requests[1].completedTasks, [first.task])

        let nextProvider = ScriptedProvider([.action(third)])
        let reopened = try makeFlow(nextProvider)
        XCTAssertEqual(reopened.screen, .currentAction(secondCard))
        try reopened.complete()
        await reopened.waitForSuggestion()
        let restoredRequests = await nextProvider.requests
        XCTAssertEqual(restoredRequests.map(\.completedTasks), [[first.task, second.task]])
    }

    func testBlankGoalCannotStart() async throws {
        let provider = ScriptedProvider([.action(first)])
        let flow = try makeFlow(provider)
        XCTAssertThrowsError(try flow.createGoal(" \n "))
        XCTAssertEqual(flow.screen, .goalInput)
        let requests = await provider.requests
        XCTAssertTrue(requests.isEmpty)
    }

    func testGoalCompletionMarkIsNotApplied() async throws {
        var marked = first
        marked.marksGoalComplete = true
        let flow = try makeFlow(ScriptedProvider([.action(marked)]))
        try flow.createGoal("기타 코드 세 개 익히기")
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .suggestionFailed(.unsuitable))
    }

    func testRepeatedCompletedActionIsNotApplied() async throws {
        var padded = first
        padded.task = "  \(first.task)\n"
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(padded)]))
        try flow.createGoal("방 한 칸 정리하기")
        await flow.waitForSuggestion()
        try flow.complete()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .suggestionFailed(.unsuitable))
    }

    func testPendingSuggestionIsInterruptedAfterReopenAndCanBeRetried() async throws {
        do {
            let flow = try makeFlow(SuspendedProvider())
            try flow.createGoal("통계 강의 1장 끝내기")
            XCTAssertEqual(flow.screen, .awaitingFirstAction)
        }

        let provider = ScriptedProvider([.action(first)])
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, .suggestionFailed(.interrupted))
        let untouched = await provider.requests
        XCTAssertTrue(untouched.isEmpty)

        try reopened.retrySuggestion()
        await reopened.waitForSuggestion()
        guard case .currentAction(let card) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(card.task, first.task)
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction])
    }

    func testProductMigrationKeepsBootstrapMetadata() throws {
        _ = try makeFlow(UnavailableSuggestionProvider())
        let value = try AppDatabase(path: path).writer.read { db in
            try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = 'schema_version'")
        }
        XCTAssertEqual(value, "1")
    }
}

private actor ScriptedProvider: ActionSuggestionProvider {
    private var candidates: [SuggestionCandidate]
    private(set) var requests: [SuggestionRequest] = []

    init(_ candidates: [SuggestionCandidate]) {
        self.candidates = candidates
    }

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        requests.append(request)
        guard !candidates.isEmpty else { throw SuggestionFailure.failed }
        return candidates.removeFirst()
    }
}

private struct SuspendedProvider: ActionSuggestionProvider {
    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        try await Task.sleep(for: .seconds(3600))
        throw SuggestionFailure.timedOut
    }
}

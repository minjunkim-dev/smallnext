import Foundation
import SQLite3
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

    private func count(_ sql: String) throws -> Int {
        try AppDatabase(path: path).writer.read { db in try Int.fetchOne(db, sql: sql) ?? 0 }
    }

    func testGoalToFirstActionToCompletionToNextActionSurvivesReopen() async throws {
        let provider = ScriptedProvider([.action(first), .action(second)])
        let secondCard: ActionCard
        do {
            let flow = try makeFlow(provider)
            XCTAssertEqual(flow.screen, .goalInput)

            try flow.createGoal("  주간 업무 보고서 초안 쓰기 ")
            XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "주간 업무 보고서 초안 쓰기", problem: nil))
            await flow.waitForSuggestion()
            guard case .currentAction(let firstCard) = flow.screen else { return XCTFail("\(flow.screen)") }
            XCTAssertEqual(firstCard.task, first.task)
            XCTAssertEqual(firstCard.doneWhen, first.doneWhen)
            XCTAssertEqual(firstCard.estimatedMinutes, first.estimatedMinutes)

            try flow.complete()
            try flow.complete()
            XCTAssertEqual(flow.screen, .awaitingNextAction(problem: nil))
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

    func testStructurallyInvalidCandidatesAreNotApplied() async throws {
        var blankTask = first
        blankTask.task = " \n"
        var blankDoneWhen = first
        blankDoneWhen.doneWhen = ""
        var noMinutes = first
        noMinutes.estimatedMinutes = 0
        var goalDone = first
        goalDone.marksGoalComplete = true
        var currentDone = first
        currentDone.marksCurrentActionComplete = true
        let invalid: [SuggestionCandidate] = [
            .action(blankTask), .action(blankDoneWhen), .action(noMinutes),
            .action(goalDone), .minimalAction(currentDone), .question("어느 자료부터 볼까요?"),
        ]
        let flow = try makeFlow(ScriptedProvider(invalid.map { .success($0) }))
        for (index, candidate) in invalid.enumerated() {
            let goal = "목표 \(index)"
            try flow.createGoal(goal)
            await flow.waitForSuggestion()
            XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: goal, problem: .unsuitable), "\(candidate)")
        }
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0)
    }

    func testRepeatedCompletedActionIsNotApplied() async throws {
        var padded = first
        padded.task = "  \(first.task)\n"
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(padded)]))
        try flow.createGoal("방 한 칸 정리하기")
        await flow.waitForSuggestion()
        try flow.complete()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingNextAction(problem: .unsuitable))
    }

    func testFirstActionFailureKeepsGoalWithoutAutomaticRetry() async throws {
        let failures = SuggestionFailure.allCases
        let provider = ScriptedProvider(failures.map { .failure($0) })
        let flow = try makeFlow(provider)
        for failure in failures {
            let goal = "목표 \(failure.rawValue)"
            try flow.createGoal(goal)
            await flow.waitForSuggestion()
            XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: goal, problem: .failure(failure)))
        }
        try await Task.sleep(for: .milliseconds(50))
        let requests = await provider.requests
        XCTAssertEqual(requests.count, failures.count)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0)
    }

    func testNextActionFailureKeepsCompletionOffline() async throws {
        let failures = SuggestionFailure.allCases
        let provider = ScriptedProvider(failures.flatMap { [.success(.action(first)), .failure($0)] })
        let flow = try makeFlow(provider)
        for failure in failures {
            try flow.createGoal("목표 \(failure.rawValue)")
            await flow.waitForSuggestion()
            try flow.complete()
            XCTAssertEqual(flow.screen, .awaitingNextAction(problem: nil))
            await flow.waitForSuggestion()
            XCTAssertEqual(flow.screen, .awaitingNextAction(problem: .failure(failure)))
        }
        try await Task.sleep(for: .milliseconds(50))
        let requests = await provider.requests
        XCTAssertEqual(requests.count, failures.count * 2)

        let reopened = try makeFlow(ScriptedProvider([SuggestionCandidate]()))
        XCTAssertEqual(reopened.screen, .awaitingNextAction(problem: .failure(failures.last!)))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), failures.count)
    }

    func testDelayedResultIsAppliedAndRetryWhileWaitingIsIgnored() async throws {
        let provider = HeldProvider(.action(first))
        let flow = try makeFlow(provider)
        try flow.createGoal("통계 강의 1장 끝내기")
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "통계 강의 1장 끝내기", problem: nil))

        try flow.retrySuggestion()
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request"), 1)

        await provider.release()
        await flow.waitForSuggestion()
        guard case .currentAction(let card) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, first.task)
        let requests = await provider.requests
        XCTAssertEqual(requests, 1)
    }

    func testCompletionWhileAnotherSuggestionIsPendingSucceeds() async throws {
        let provider = ScriptedProvider([.action(first), .action(second)])
        let flow = try makeFlow(provider)
        try flow.createGoal("주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        // 더 작게(#55) 같은 다른 종류의 요청이 기다리는 상태를 만든다.
        try await AppDatabase(path: path).writer.write { db in
            try db.execute(sql: """
                INSERT INTO suggestion_request (goal_id, kind, goal_revision, status, created_at)
                SELECT id, 'smaller', revision, 'pending', CURRENT_TIMESTAMP FROM goal
                """)
        }

        try flow.complete()
        XCTAssertEqual(flow.screen, .awaitingNextAction(problem: nil))
        await flow.waitForSuggestion()
        guard case .currentAction(let card) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, second.task)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 1)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request WHERE kind = 'smaller' AND status = 'interrupted'"), 1)
    }

    func testCancelReachesProviderAndKeepsGoal() async throws {
        let provider = SuspendedProvider()
        let flow = try makeFlow(provider)
        try flow.createGoal("통계 강의 1장 끝내기")
        try flow.cancelSuggestion()
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "통계 강의 1장 끝내기", problem: .cancelled))
        await flow.waitForSuggestion()
        let cancelled = await provider.cancelled
        XCTAssertTrue(cancelled)
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "통계 강의 1장 끝내기", problem: .cancelled))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'cancelled'"), 1)
    }

    func testResultArrivingAfterCancelIsNotApplied() async throws {
        let provider = HeldProvider(.action(first))
        let flow = try makeFlow(provider)
        try flow.createGoal("방 한 칸 정리하기")
        try flow.cancelSuggestion()
        await provider.release()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "방 한 칸 정리하기", problem: .cancelled))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0)
    }

    func testResultForChangedRevisionIsNotApplied() async throws {
        let provider = HeldProvider(.action(first))
        let flow = try makeFlow(provider)
        try flow.createGoal("방 한 칸 정리하기")
        try await AppDatabase(path: path).writer.write { db in
            try db.execute(sql: "UPDATE goal SET revision = revision + 1")
        }
        await provider.release()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "방 한 칸 정리하기", problem: .interrupted))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0)
    }

    func testPendingSuggestionIsInterruptedAfterReopenAndCanBeRetried() async throws {
        do {
            let flow = try makeFlow(SuspendedProvider())
            try flow.createGoal("통계 강의 1장 끝내기")
            XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "통계 강의 1장 끝내기", problem: nil))
        }

        let provider = ScriptedProvider([.action(first)])
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, .awaitingFirstAction(goal: "통계 강의 1장 끝내기", problem: .interrupted))
        let untouched = await provider.requests
        XCTAssertTrue(untouched.isEmpty)

        try reopened.retrySuggestion()
        await reopened.waitForSuggestion()
        guard case .currentAction(let card) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(card.task, first.task)
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction])
    }

    func testPendingNextActionIsInterruptedAfterReopenAndKeepsCompletion() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first)]))
        try flow.createGoal("주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        do {
            let waiting = try makeFlow(SuspendedProvider())
            try waiting.complete()
            XCTAssertEqual(waiting.screen, .awaitingNextAction(problem: nil))
        }

        let reopened = try makeFlow(ScriptedProvider([SuggestionCandidate]()))
        XCTAssertEqual(reopened.screen, .awaitingNextAction(problem: .interrupted))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 1)
    }

    func testUnsavedSuggestionResultShowsFailureAndCanBeRetried() async throws {
        let provider = LockingProvider(path: path, candidate: .action(first))
        let flow = try makeFlow(provider)
        try flow.createGoal("주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "주간 업무 보고서 초안 쓰기", problem: .failure(.failed)))

        await provider.releaseLock()
        try flow.retrySuggestion()
        await flow.waitForSuggestion()
        guard case .currentAction(let card) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, first.task)
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
    private var outcomes: [Result<SuggestionCandidate, SuggestionFailure>]
    private(set) var requests: [SuggestionRequest] = []

    init(_ outcomes: [Result<SuggestionCandidate, SuggestionFailure>]) {
        self.outcomes = outcomes
    }

    init(_ candidates: [SuggestionCandidate]) {
        self.init(candidates.map { .success($0) })
    }

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        requests.append(request)
        guard !outcomes.isEmpty else { throw SuggestionFailure.failed }
        return try outcomes.removeFirst().get()
    }
}

/// `release()` 전까지 결과를 붙잡는다. 취소를 무시해 늦게 도착한 결과를 만든다.
private actor HeldProvider: ActionSuggestionProvider {
    private let candidate: SuggestionCandidate
    private var gate: CheckedContinuation<Void, Never>?
    private(set) var requests = 0

    init(_ candidate: SuggestionCandidate) {
        self.candidate = candidate
    }

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        requests += 1
        await withCheckedContinuation { gate = $0 }
        return candidate
    }

    func release() async {
        for _ in 0..<10_000 where gate == nil { await Task.yield() }
        gate?.resume()
        gate = nil
    }
}

/// 첫 요청에서 다른 연결로 쓰기 잠금을 잡는다. 결과 저장이 실패하는 경우를 만든다.
/// GRDB는 열린 트랜잭션을 남길 수 없어 SQLite C API를 쓴다.
private actor LockingProvider: ActionSuggestionProvider {
    private let path: String
    private let candidate: SuggestionCandidate
    private var lock: OpaquePointer?
    private var locked = false

    init(path: String, candidate: SuggestionCandidate) {
        self.path = path
        self.candidate = candidate
    }

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        if !locked {
            locked = true
            guard sqlite3_open(path, &lock) == SQLITE_OK,
                  sqlite3_exec(lock, "BEGIN EXCLUSIVE", nil, nil, nil) == SQLITE_OK
            else { throw SuggestionFailure.failed }
        }
        return candidate
    }

    func releaseLock() {
        sqlite3_exec(lock, "ROLLBACK", nil, nil, nil)
        sqlite3_close(lock)
        lock = nil
    }
}

private actor SuspendedProvider: ActionSuggestionProvider {
    private(set) var cancelled = false

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        do {
            try await Task.sleep(for: .seconds(3600))
        } catch {
            cancelled = true
            throw error
        }
        throw SuggestionFailure.timedOut
    }
}

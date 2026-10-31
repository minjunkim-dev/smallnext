import Foundation
import SQLite3
import XCTest
@testable import SmallnextCore

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

    /// 목표 준비 요청은 `GoalPreparing`이 답한다. 준비 결과를 직접 검사하는 테스트는 `preparing: false`를 쓴다.
    private func makeFlow(_ provider: any ActionSuggestionProvider, preparing: Bool = true) throws -> ProgressFlow {
        try ProgressFlow(database: AppDatabase(path: path), provider: preparing ? GoalPreparing(wrapped: provider) : provider)
    }

    /// 사용자 경로로 목표를 입력하고 준비한다. 완료 조건을 확인하기 직전에서 멈춘다.
    private func prepareGoal(_ flow: ProgressFlow, _ statement: String) async throws {
        if flow.screen != .goalInput { try flow.startNewGoal() }
        var input = GoalInput()
        input.statement = statement
        try flow.updateGoalInput(input)
        try flow.prepareGoal()
        await flow.waitForSuggestion()
    }

    /// 사용자 경로로 목표를 준비하고 완료 조건을 확인한다. 첫 행동 요청이 시작된 상태로 끝난다.
    private func startGoal(_ flow: ProgressFlow, _ statement: String) async throws {
        try await prepareGoal(flow, statement)
        try flow.confirmGoal(completionCriteria: statement)
    }

    func testTimingWaitsForScreenObservationAndDoesNotChangeProgress() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
        flow.timingEnabled = true
        try await prepareGoal(flow, "학습 자료 정리")
        try flow.run { try flow.confirmGoal(completionCriteria: "학습 자료 정리") }
        await flow.waitForSuggestion()
        let firstSample = try XCTUnwrap(flow.timingSample)
        XCTAssertEqual(firstSample.kind, .firstAction)
        XCTAssertEqual(firstSample.outcome, "action")
        XCTAssertNil(firstSample.snapshot().screenUpperBoundMS)
        XCTAssertNotNil(firstSample.snapshot().applyMS)
        XCTAssertNil(firstSample.snapshot().httpMS)
        try flow.run { try flow.makeSmaller() }
        await flow.waitForSuggestion()
        XCTAssertNotEqual(flow.timingSample?.id, firstSample.id)
        XCTAssertEqual(flow.timingSample?.kind, .smaller)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 0)
    }

    func testTimingCancellationAndLateResponseDoNotMarkAnotherScreen() async throws {
        let provider = HeldProvider(.action(first))
        let flow = try makeFlow(provider)
        flow.timingEnabled = true
        try await prepareGoal(flow, "資料 정리")
        try flow.run { try flow.confirmGoal(completionCriteria: "資料 정리") }
        try flow.cancelSuggestion()
        try flow.startNewGoal()
        await provider.release()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .goalInput)
        XCTAssertNil(flow.timingSample)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 0)
    }

    func testTimingStorageFailureDoesNotBecomeNormalSample() async throws {
        let provider = LockingProvider(path: path, candidate: .action(first))
        let flow = try makeFlow(provider)
        flow.timingEnabled = true
        try await prepareGoal(flow, "자료 정리")
        try flow.run { try flow.confirmGoal(completionCriteria: "자료 정리") }
        await flow.waitForSuggestion()
        XCTAssertNil(flow.timingSample)
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "자료 정리", problem: .failure(.failed)))
        await provider.releaseLock()
    }

    func testTimingCancelledLateResponseCannotMarkStoppedGoal() async throws {
        let provider = HeldProvider(.action(first))
        let flow = try makeFlow(provider)
        flow.timingEnabled = true
        try await prepareGoal(flow, "자료 정리")
        try flow.run { try flow.confirmGoal(completionCriteria: "자료 정리") }
        try flow.cancelSuggestion()
        try flow.stopGoal()
        await provider.release()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .stoppedGoal(nil))
        XCTAssertNil(flow.timingSample)
    }

    func testRemainingSplitWorkSurvivesTwoNextActionsAndReopen() async throws {
        let fourth = ProposedAction(task: "자료 저장하기", doneWhen: "자료가 저장됐다", estimatedMinutes: 1)
        let fifth = ProposedAction(task: "자료 위치 확인하기", doneWhen: "위치를 확인했다", estimatedMinutes: 1)
        let provider = ScriptedProvider([.action(first), .action(second), .action(third), .action(fourth), .action(fifth)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "학습 자료 정리")
        await flow.waitForSuggestion()
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        try flow.complete()
        await flow.waitForSuggestion()
        try flow.complete()
        await flow.waitForSuggestion()
        let requests = await provider.requests
        XCTAssertTrue(requests.last!.remainingTasks.contains(first.task))
        XCTAssertEqual(requests.last!.completedActionIDs.count, 2)
        XCTAssertFalse(requests.last!.stateKey.isEmpty)
        let reopened = try makeFlow(provider)
        try reopened.complete()
        await reopened.waitForSuggestion()
        let recovered = await provider.requests
        XCTAssertTrue(recovered.last!.remainingTasks.contains(first.task))
        XCTAssertEqual(recovered.last!.completedActionIDs.count, 3)
    }

    private func count(_ sql: String) throws -> Int {
        try AppDatabase(path: path).writer.read { db in try Int.fetchOne(db, sql: sql) ?? 0 }
    }

    func testSwitchingGoalsPreservesActionsDraftsResultsAndSelection() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(second), .action(third)]))
        try await startGoal(flow, "학습 자료 정리")
        await flow.waitForSuggestion()
        let firstGoal = try XCTUnwrap(flow.goalDetails?.id)
        guard case .currentAction(let card, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.recordResult("첫 자료 확인", for: card.id)
        try flow.complete()
        await flow.waitForSuggestion()
        guard case .currentAction(let next, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.updateDraft("학습 목표 초안", for: next.id)
        let firstScreen = flow.screen
        try await startGoal(flow, "화분 옮기기")
        await flow.waitForSuggestion()
        let secondGoal = try XCTUnwrap(flow.goalDetails?.id)
        guard case .currentAction(let other, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.updateDraft("화분 목표 초안", for: other.id)
        let secondScreen = flow.screen
        try flow.selectGoal(firstGoal)
        XCTAssertEqual(flow.screen, firstScreen)
        XCTAssertEqual(flow.goals.first(where: { $0.id == firstGoal })?.completedActionCount, 1)
        let reopened = try makeFlow(UnavailableSuggestionProvider())
        XCTAssertEqual(reopened.goalDetails?.id, firstGoal)
        XCTAssertEqual(reopened.screen, firstScreen)
        try reopened.selectGoal(secondGoal)
        XCTAssertEqual(reopened.screen, secondScreen)
        XCTAssertEqual(reopened.goals.count, 2)
    }

    func testNewGoalInputSurvivesSwitchingAndConfirmationOfAnotherGoal() async throws {
        let flow = try makeFlow(ScriptedProvider([.goalSummary("학습을 끝냈다"), .action(first)]), preparing: false)
        let input = GoalInput(statement: "학습하기", currentState: "첫 단원 선택")
        try flow.updateGoalInput(input)
        try flow.prepareGoal()
        await flow.waitForSuggestion()
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        try flow.startNewGoal()
        XCTAssertEqual(flow.screen, .goalInput)
        XCTAssertEqual(flow.goalInput, GoalInput())
        let newInput = GoalInput(statement: "화분 옮기기", blocker: "흙이 없다")
        try flow.updateGoalInput(newInput)
        try flow.selectGoal(goalID)
        XCTAssertEqual(flow.goalInput, input)
        try flow.confirmGoal(completionCriteria: "첫 단원을 설명한다")
        await flow.waitForSuggestion()
        try flow.startNewGoal()
        let reopened = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        XCTAssertEqual(reopened.screen, .goalInput)
        XCTAssertEqual(reopened.goalInput, newInput)
        XCTAssertEqual(reopened.goals.count, 1)
    }

    func testGoalStatementEditKeepsProgressAndRejectsLateSuggestion() async throws {
        let seed = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
        try await startGoal(seed, "메모 정리")
        await seed.waitForSuggestion()
        try seed.complete()
        await seed.waitForSuggestion()
        guard case .currentAction(let card, nil) = seed.screen else { return XCTFail("\(seed.screen)") }
        try seed.recordResult("이미 남긴 결과", for: card.id)
        try seed.updateDraft("작성 중", for: card.id)
        let held = HeldProvider(.action(third))
        let flow = try makeFlow(held)
        try flow.makeSmaller()
        XCTAssertThrowsError(try flow.editGoalStatement(" \n "))
        try flow.editGoalStatement("  학습 메모 정리  ")
        await held.release()
        await flow.waitForSuggestion()
        guard case .currentAction(let kept, .problem(.interrupted)) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(kept.id, card.id)
        XCTAssertEqual(kept.draft, "작성 중")
        XCTAssertEqual(kept.results.map(\.body), ["이미 남긴 결과"])
        XCTAssertEqual(flow.goals.first?.completedActionCount, 1)
        XCTAssertEqual(flow.goalDetails?.statement, "학습 메모 정리")
        XCTAssertEqual(try makeFlow(UnavailableSuggestionProvider()).screen, flow.screen)
    }

    func testSwitchingGoalsInterruptsPreviousRequestWithoutApplyingLateResponse() async throws {
        let seed = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
        try await startGoal(seed, "학습")
        await seed.waitForSuggestion()
        let firstID = try XCTUnwrap(seed.goalDetails?.id)
        try await startGoal(seed, "화분")
        await seed.waitForSuggestion()
        let secondID = try XCTUnwrap(seed.goalDetails?.id)
        let secondScreen = seed.screen
        let held = HeldProvider(.action(third))
        let flow = try makeFlow(held)
        try flow.selectGoal(firstID)
        try flow.complete()
        try flow.selectGoal(secondID)
        await held.release()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, secondScreen)
        try flow.selectGoal(firstID)
        XCTAssertEqual(flow.screen, .awaitingNextAction(problem: .interrupted))
        XCTAssertEqual(flow.goals.first?.completedActionCount, 1)
    }

    func testStoppingGoalKeepsRecordsAndPreventsLateResponseAndFurtherProgress() async throws {
        let seed = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
        try await startGoal(seed, "학습 자료 정리")
        await seed.waitForSuggestion()
        try seed.complete()
        await seed.waitForSuggestion()
        guard case .currentAction(let card, nil) = seed.screen else { return XCTFail("\(seed.screen)") }
        try seed.recordResult("보관할 결과", for: card.id)
        try seed.updateDraft("보관할 초안", for: card.id)
        let held = HeldProvider(.action(third))
        let flow = try makeFlow(held)
        try flow.makeSmaller()
        try flow.stopGoal()
        await held.release()
        await flow.waitForSuggestion()
        guard case .stoppedGoal(let saved) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(saved?.id, card.id)
        XCTAssertEqual(saved?.draft, "보관할 초안")
        XCTAssertEqual(saved?.results.map(\.body), ["보관할 결과"])
        XCTAssertEqual(flow.goals.first?.completedActionCount, 1)
        XCTAssertEqual(flow.goals.first?.isStopped, true)
        let stopped = flow.screen
        try flow.complete()
        try flow.retrySuggestion()
        try flow.makeSmaller()
        XCTAssertEqual(flow.screen, stopped)
        XCTAssertEqual(try makeFlow(UnavailableSuggestionProvider()).screen, stopped)
    }

    func testDeletingGoalRequiresConfirmationAndPreservesOtherGoalAndNewInput() async throws {
        let seed = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
        try seed.updateGoalInput(GoalInput(statement: "삭제할 목표"))
        try seed.prepareGoal()
        await seed.waitForSuggestion()
        let deletedID = try XCTUnwrap(seed.goalDetails?.id)
        try seed.confirmGoal(completionCriteria: "자료가 정리됐다")
        await seed.waitForSuggestion()
        try await startGoal(seed, "보관할 목표")
        await seed.waitForSuggestion()
        let keptID = try XCTUnwrap(seed.goalDetails?.id)
        guard case .currentAction(let keptCard, nil) = seed.screen else { return XCTFail("\(seed.screen)") }
        try seed.recordResult("다른 목표의 결과", for: keptCard.id)
        try seed.updateDraft("다른 목표의 초안", for: keptCard.id)
        let keptScreen = seed.screen
        try seed.startNewGoal()
        let newInput = GoalInput(statement: "아직 제출하지 않은 목표")
        try seed.updateGoalInput(newInput)
        let held = HeldProvider(.action(third))
        let flow = try makeFlow(held, preparing: false)
        try flow.selectGoal(deletedID)
        try flow.complete()
        XCTAssertThrowsError(try flow.deleteGoal(deletedID))
        XCTAssertTrue(flow.screen.isWaitingForSuggestion)
        XCTAssertEqual(flow.goals.count, 2)
        try flow.deleteGoal(deletedID, confirmed: true)
        await held.release()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .goalInput)
        XCTAssertEqual(flow.goalInput, newInput)
        XCTAssertEqual(flow.goals.map(\.id), [keptID])
        XCTAssertThrowsError(try flow.selectGoal(deletedID))
        let reopened = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        XCTAssertThrowsError(try reopened.selectGoal(deletedID))
        try reopened.selectGoal(keptID)
        XCTAssertEqual(reopened.screen, keptScreen)
    }

    func testFailedGoalChangesKeepSelectionRecordsAndLiveRequest() async throws {
        let seed = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
        try await startGoal(seed, "수정 실패 시 보관할 목표")
        await seed.waitForSuggestion()
        let goalID = try XCTUnwrap(seed.goalDetails?.id)
        try await startGoal(seed, "다른 목표")
        await seed.waitForSuggestion()
        let held = HeldProvider(.action(third))
        let flow = try makeFlow(held)
        try flow.selectGoal(goalID)
        try flow.complete()
        let before = flow.screen
        let goals = flow.goals
        let database = try AppDatabase(path: path)
        try await database.writer.write { db in
            try db.execute(sql: "CREATE TRIGGER reject_goal_update BEFORE UPDATE ON goal BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            try db.execute(sql: "CREATE TRIGGER reject_selection_delete BEFORE DELETE ON app_metadata WHEN OLD.key = 'selected_goal_id' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        }
        XCTAssertThrowsError(try flow.selectGoal(-1))
        XCTAssertThrowsError(try flow.editGoalStatement("적용하면 안 되는 문구"))
        XCTAssertThrowsError(try flow.stopGoal())
        XCTAssertThrowsError(try flow.deleteGoal(goalID, confirmed: true))
        XCTAssertEqual(flow.screen, before)
        XCTAssertEqual(flow.goals, goals)
        XCTAssertEqual(flow.goalDetails?.id, goalID)
        try await database.writer.write { db in
            try db.execute(sql: "DROP TRIGGER reject_goal_update")
            try db.execute(sql: "DROP TRIGGER reject_selection_delete")
        }
        await held.release()
        await flow.waitForSuggestion()
        guard case .currentAction(let card, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, third.task)
        XCTAssertEqual(flow.goals.first?.completedActionCount, 1)
        XCTAssertEqual(try makeFlow(UnavailableSuggestionProvider()).screen, flow.screen)
    }

    func testLegacyGoalPreparationInputMigratesWithoutLosingContext() async throws {
        let input = GoalInput(statement: "학습하기", deadline: "이번 주", materialExcerpt: "선택한 내용")
        do {
            let flow = try makeFlow(ScriptedProvider([.goalSummary("첫 단원을 끝냈다")]), preparing: false)
            try flow.updateGoalInput(input)
            try flow.prepareGoal()
            await flow.waitForSuggestion()
            let goalID = try XCTUnwrap(flow.goalDetails?.id)
            // #58의 저장 형식을 만든다. 관찰은 진행 흐름의 공개 상태에서만 한다.
            let database = try AppDatabase(path: path)
            try await database.writer.write { db in
                try db.execute(sql: "DELETE FROM grdb_migrations WHERE identifier = 'progress_v5_goal_input_scope'")
                try db.execute(sql: "UPDATE app_metadata SET key = 'goal_input' WHERE key = ?", arguments: ["goal_input:\(goalID)"])
            }
        }
        let reopened = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        XCTAssertEqual(reopened.goalInput, input)
        XCTAssertEqual(reopened.screen, .preparingGoal(question: nil, completionCriteria: "첫 단원을 끝냈다", problem: nil))
        try reopened.startNewGoal()
        XCTAssertEqual(reopened.goalInput, GoalInput())
    }

    func testDeletingUnconfirmedGoalKeepsNewDraftAndRejectsLateSummary() async throws {
        let held = HeldProvider(.goalSummary("삭제한 목표의 요약"))
        let flow = try makeFlow(held, preparing: false)
        try flow.updateGoalInput(GoalInput(statement: "삭제할 입력", materialExcerpt: "삭제할 발췌"))
        try flow.prepareGoal()
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        try flow.startNewGoal()
        let draft = GoalInput(statement: "보관할 새 입력")
        try flow.updateGoalInput(draft)
        try flow.deleteGoal(goalID, confirmed: true)
        await held.release()
        await flow.waitForSuggestion()
        let reopened = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        XCTAssertEqual(reopened.screen, .goalInput)
        XCTAssertEqual(reopened.goalInput, draft)
        XCTAssertTrue(reopened.goals.isEmpty)
        XCTAssertThrowsError(try reopened.selectGoal(goalID))
    }

    func testSuggestionInputDraftsSurviveGoalSwitchAndReopenAndRejectStaleInput() async throws {
        let flow = try makeFlow(ScriptedProvider([.question("어떤 자료인가요?"), .goalSummary("자료를 정리했다")]), preparing: false)
        try flow.updateGoalInput(GoalInput(statement: "학습 자료 정리"))
        try flow.prepareGoal()
        await flow.waitForSuggestion()
        let firstID = try XCTUnwrap(flow.goalDetails?.id)
        let firstRequest = try XCTUnwrap(flow.suggestionInput?.requestID)
        try flow.updateSuggestionInput("질문 답을 작성 중", for: firstRequest)
        try flow.startNewGoal()
        try flow.updateGoalInput(GoalInput(statement: "화분 옮기기"))
        try flow.prepareGoal()
        await flow.waitForSuggestion()
        let secondID = try XCTUnwrap(flow.goalDetails?.id)
        let secondRequest = try XCTUnwrap(flow.suggestionInput?.requestID)
        try flow.updateSuggestionInput("화분이 새 자리에 있다", for: secondRequest)
        XCTAssertThrowsError(try flow.updateSuggestionInput("다른 질문의 늦은 입력", for: firstRequest))
        try flow.selectGoal(firstID)
        let reopened = try makeFlow(ScriptedProvider([.action(first)]))
        XCTAssertEqual(reopened.suggestionInput?.text, "질문 답을 작성 중")
        try reopened.selectGoal(secondID)
        XCTAssertEqual(reopened.suggestionInput?.text, "화분이 새 자리에 있다")
        try reopened.confirmGoal(completionCriteria: "화분이 새 자리에 있다")
        await reopened.waitForSuggestion()
        XCTAssertNil(reopened.suggestionInput)
        XCTAssertThrowsError(try reopened.updateSuggestionInput("이전 완료 조건", for: secondRequest))
        XCTAssertEqual(reopened.goalDetails?.completionCriteria, "화분이 새 자리에 있다")
    }

    func testGoalInputDraftSurvivesReopenBeforeSubmission() throws {
        let input = GoalInput(statement: "화분 옮기기", deadline: "이번 주", currentState: "화분은 골랐다",
                              blocker: "흙이 있는지 모른다", materialLinks: "https://example.com/plant",
                              materialExcerpt: "사용자가 고른 요약", availableMinutes: "15")
        do {
            let flow = try makeFlow(UnavailableSuggestionProvider())
            try flow.updateGoalInput(input)
            XCTAssertEqual(flow.screen, .goalInput)
        }
        let reopened = try makeFlow(UnavailableSuggestionProvider())
        XCTAssertEqual(reopened.goalInput, input)
        XCTAssertNil(reopened.goalDetails)
    }

    func testGoalContextIsSentAndFirstActionWaitsForConfirmation() async throws {
        let provider = ScriptedProvider([.goalSummary("화분 하나를 옮겼다"), .action(first)])
        let flow = try makeFlow(provider, preparing: false)
        let input = GoalInput(statement: " 화분 옮기기 ", deadline: "이번 주", currentState: "화분은 골랐다",
                              blocker: "흙이 있는지 모른다", materialLinks: "https://example.com/plant",
                              materialExcerpt: "고른 발췌만 보낸다", availableMinutes: "15")
        try flow.updateGoalInput(input)
        try flow.prepareGoal()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .preparingGoal(question: nil, completionCriteria: "화분 하나를 옮겼다", problem: nil))
        XCTAssertNil(flow.goalDetails?.completionCriteria)
        var requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.goalPreparation])
        XCTAssertEqual(requests[0].context.currentState, "화분은 골랐다")
        XCTAssertEqual(requests[0].context.deadline, "이번 주")
        XCTAssertEqual(requests[0].context.materialLinks, [URL(string: "https://example.com/plant")!])
        XCTAssertEqual(requests[0].context.materialExcerpt, "고른 발췌만 보낸다")
        XCTAssertEqual(requests[0].context.availableMinutes, 15)
        XCTAssertEqual(requests[0].blocker, "흙이 있는지 모른다")
        try flow.confirmGoal(completionCriteria: "화분 하나가 새 자리에 있다")
        await flow.waitForSuggestion()
        guard case .currentAction = flow.screen else { return XCTFail("\(flow.screen)") }
        requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.goalPreparation, .firstAction])
        XCTAssertEqual(requests[1].completionCriteria, "화분 하나가 새 자리에 있다")
        XCTAssertEqual(requests[1].context, requests[0].context)
        let reopened = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        XCTAssertEqual(reopened.goalDetails?.statement, "화분 옮기기")
        XCTAssertEqual(reopened.goalDetails?.completionCriteria, "화분 하나가 새 자리에 있다")
        XCTAssertEqual(reopened.goalDetails?.context, requests[0].context)
    }

    func testGoalQuestionAnswerSurvivesReopenAndIsNotAskedAgain() async throws {
        let question = "무엇을 정리하려고 하나요?"
        do {
            let flow = try makeFlow(ScriptedProvider([.question(question)]), preparing: false)
            try flow.updateGoalInput(GoalInput(statement: "정리하기"))
            try flow.prepareGoal()
            await flow.waitForSuggestion()
            XCTAssertEqual(flow.screen, .preparingGoal(question: question, completionCriteria: nil, problem: nil))
        }
        let provider = ScriptedProvider([.question(question), .goalSummary("화분 자리를 정했다")])
        let reopened = try makeFlow(provider, preparing: false)
        XCTAssertEqual(reopened.screen, .preparingGoal(question: question, completionCriteria: nil, problem: nil))
        XCTAssertThrowsError(try reopened.answerGoalQuestion(" \n"))
        try reopened.answerGoalQuestion("화분 자리")
        await reopened.waitForSuggestion()
        XCTAssertEqual(reopened.screen, .preparingGoal(question: nil, completionCriteria: nil, problem: .unsuitable))
        try reopened.retrySuggestion()
        await reopened.waitForSuggestion()
        XCTAssertEqual(reopened.screen, .preparingGoal(question: nil, completionCriteria: "화분 자리를 정했다", problem: nil))
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.goalPreparation, .goalPreparation])
        XCTAssertEqual(requests[1].context.answers, [GoalAnswer(question: question, answer: "화분 자리")])
        XCTAssertNil(requests[1].context.currentState)
        XCTAssertNil(requests[1].blocker)
        let again = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        XCTAssertEqual(again.screen, reopened.screen)
        XCTAssertEqual(again.goalDetails?.context.answers, requests[1].context.answers)
        XCTAssertNil(again.goalDetails?.completionCriteria)
    }

    func testGoalPreparationInterruptedOnReopenKeepsInputAndCanRetry() async throws {
        let input = GoalInput(statement: "기초 단원 학습하기", availableMinutes: "10")
        let held = HeldProvider(.goalSummary("기초 개념을 설명할 수 있다"))
        let flow = try makeFlow(held, preparing: false)
        try flow.updateGoalInput(input)
        try flow.prepareGoal()
        XCTAssertTrue(flow.screen.isWaitingForSuggestion)
        XCTAssertThrowsError(try flow.confirmGoal(completionCriteria: "아직 확인하지 않았다"))
        let provider = ScriptedProvider([.goalSummary("학습한 내용을 설명할 수 있다")])
        let reopened = try makeFlow(provider, preparing: false)
        XCTAssertEqual(reopened.goalInput, input)
        XCTAssertEqual(reopened.screen, .preparingGoal(question: nil, completionCriteria: nil, problem: .interrupted))
        let before = await provider.requests
        XCTAssertTrue(before.isEmpty)
        await held.release()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, reopened.screen)
        try reopened.retrySuggestion()
        await reopened.waitForSuggestion()
        XCTAssertEqual(reopened.screen, .preparingGoal(question: nil, completionCriteria: "학습한 내용을 설명할 수 있다", problem: nil))
        XCTAssertNil(reopened.goalDetails?.context.currentState)
        XCTAssertNil(reopened.goalDetails?.completionCriteria)
    }

    func testInvalidOptionalInputStaysInDraftWithoutRequestingProvider() async throws {
        let provider = ScriptedProvider([.goalSummary("정리를 마쳤다")])
        let flow = try makeFlow(provider, preparing: false)
        for input in [GoalInput(statement: "정리", materialLinks: "file:///private/tmp/file"),
                      GoalInput(statement: "정리", availableMinutes: "-3"),
                      GoalInput(statement: "정리", availableMinutes: "abc")] {
            try flow.updateGoalInput(input)
            XCTAssertThrowsError(try flow.prepareGoal())
            XCTAssertEqual(flow.goalInput, input)
            XCTAssertEqual(flow.screen, .goalInput)
        }
        let requests = await provider.requests
        XCTAssertTrue(requests.isEmpty)
    }

    func testWhitespaceOnlyOptionalLinkIsTreatedAsEmpty() async throws {
        let provider = ScriptedProvider([.goalSummary("메모를 정리했다")])
        let flow = try makeFlow(provider, preparing: false)
        try flow.updateGoalInput(GoalInput(statement: "메모 정리", materialLinks: " \n\t "))
        try flow.prepareGoal()
        await flow.waitForSuggestion()
        let requests = await provider.requests
        XCTAssertEqual(requests.count, 1)
        XCTAssertTrue(try XCTUnwrap(requests.first).context.materialLinks.isEmpty)
    }

    func testGoalPreparationCannotApplyActionBeforeConfirmation() async throws {
        let provider = ScriptedProvider([.action(first), .goalSummary("메모를 정리했다")])
        let flow = try makeFlow(provider, preparing: false)
        try flow.updateGoalInput(GoalInput(statement: "메모 정리"))
        try flow.prepareGoal()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .preparingGoal(question: nil, completionCriteria: nil, problem: .unsuitable))
        XCTAssertThrowsError(try flow.confirmGoal(completionCriteria: "확인되지 않은 조건"))
        try flow.retrySuggestion()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .preparingGoal(question: nil, completionCriteria: "메모를 정리했다", problem: nil))
        XCTAssertNil(flow.goalDetails?.context.currentState)
        XCTAssertNil(flow.goalDetails?.completionCriteria)
    }

    func testGoalConfirmationFailureKeepsReviewAndInputAndCanRetry() async throws {
        let provider = ScriptedProvider([.goalSummary("메모를 정리했다"), .action(first)])
        let flow = try makeFlow(provider, preparing: false)
        let input = GoalInput(statement: "메모 정리", materialExcerpt: "선택한 한 줄")
        try flow.updateGoalInput(input)
        try flow.prepareGoal()
        await flow.waitForSuggestion()
        let before = flow.screen
        let database = try AppDatabase(path: path)
        try await database.writer.write { db in
            try db.execute(sql: "CREATE TRIGGER fail_goal_confirmation BEFORE INSERT ON suggestion_request WHEN NEW.kind = 'first_action' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        }
        XCTAssertThrowsError(try flow.confirmGoal(completionCriteria: "사용자가 확인한 조건"))
        XCTAssertEqual(flow.screen, before)
        XCTAssertEqual(flow.goalInput, input)
        XCTAssertNil(flow.goalDetails?.completionCriteria)
        let reopened = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        XCTAssertEqual(reopened.screen, before)
        XCTAssertEqual(reopened.goalInput, input)
        try await database.writer.write { db in try db.execute(sql: "DROP TRIGGER fail_goal_confirmation") }
        try flow.confirmGoal(completionCriteria: "사용자가 확인한 조건")
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.goalDetails?.completionCriteria, "사용자가 확인한 조건")
        XCTAssertEqual(flow.goalInput, GoalInput())
        guard case .currentAction = flow.screen else { return XCTFail("\(flow.screen)") }
    }

    func testGoalToFirstActionToCompletionToNextActionSurvivesReopen() async throws {
        let provider = ScriptedProvider([.action(first), .action(second)])
        let secondCard: ActionCard
        do {
            let flow = try makeFlow(provider)
            XCTAssertEqual(flow.screen, .goalInput)

            try await startGoal(flow, "  주간 업무 보고서 초안 쓰기 ")
            XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "주간 업무 보고서 초안 쓰기", problem: nil))
            await flow.waitForSuggestion()
            guard case .currentAction(let firstCard, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
            XCTAssertEqual(firstCard.task, first.task)
            XCTAssertEqual(firstCard.doneWhen, first.doneWhen)
            XCTAssertEqual(firstCard.estimatedMinutes, first.estimatedMinutes)

            try flow.complete()
            try flow.complete()
            XCTAssertEqual(flow.screen, .awaitingNextAction(problem: nil))
            await flow.waitForSuggestion()
            guard case .currentAction(let card, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
            XCTAssertEqual(card.task, second.task)
            secondCard = card
        }

        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction, .nextAction])
        XCTAssertEqual(requests[0].goal, "주간 업무 보고서 초안 쓰기")
        XCTAssertEqual(requests[1].completedTasks, [first.task])

        let nextProvider = ScriptedProvider([.action(third)])
        let reopened = try makeFlow(nextProvider)
        XCTAssertEqual(reopened.screen, .currentAction(secondCard, smaller: nil))
        try reopened.complete()
        await reopened.waitForSuggestion()
        let restoredRequests = await nextProvider.requests
        XCTAssertEqual(restoredRequests.map(\.completedTasks), [[first.task, second.task]])
    }

    func testBlankGoalCannotStart() async throws {
        let provider = ScriptedProvider([.action(first)])
        let flow = try makeFlow(provider, preparing: false)
        var input = GoalInput()
        input.statement = " \n "
        try flow.updateGoalInput(input)
        XCTAssertThrowsError(try flow.prepareGoal())
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
            .action(goalDone), .minimalAction(currentDone), .question(" \n"),
        ]
        let flow = try makeFlow(ScriptedProvider(invalid.map { .success($0) }))
        for (index, candidate) in invalid.enumerated() {
            let goal = "목표 \(index)"
            try await startGoal(flow, goal)
            await flow.waitForSuggestion()
            XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: goal, problem: .unsuitable), "\(candidate)")
        }
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0)
    }

    func testRepeatedCompletedActionIsNotApplied() async throws {
        var padded = first
        padded.task = "  \(first.task)\n"
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(padded)]))
        try await startGoal(flow, "방 한 칸 정리하기")
        await flow.waitForSuggestion()
        try flow.complete()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingNextAction(problem: .unsuitable))
    }

    func testSupplementalDraftAndConfirmationRestoreSeparatelyWithoutCallingProvider() async throws {
        let provider = ScriptedProvider([.insufficientInfo(try InsufficientInfoFixture.reason())])
        let flow = try makeFlow(provider)
        try await prepareGoal(flow, "과거 경력 사실 정리")
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        XCTAssertNil(flow.supplementalContext)
        try flow.confirmGoal(completionCriteria: "경력 사실을 정리했다")
        await flow.waitForSuggestion()
        let notice = try XCTUnwrap(flow.supplementalContext?.lastNotice)
        XCTAssertNil(flow.supplementalContext?.draftText)
        try flow.updateSupplementalDraft("", for: goalID)
        XCTAssertEqual(flow.supplementalContext?.draftText, "")
        let text = "당시 제가 작성한 것은 첫 문단이에요.\n자료는 직접 골랐어요."
        try flow.updateSupplementalDraft(text, for: goalID)
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.supplementalContext?.draftText, text)
        XCTAssertEqual(reopened.supplementalContext?.confirmedText, "")
        XCTAssertFalse(try XCTUnwrap(reopened.supplementalContext).hasChangesSinceNotice)
        XCTAssertEqual(try count("SELECT revision FROM goal WHERE id = \(goalID)"), notice.goalRevision)
        try reopened.confirmSupplementalContext(text, for: goalID)
        XCTAssertEqual(reopened.supplementalContext?.confirmedText, text)
        XCTAssertNil(reopened.supplementalContext?.draftText)
        XCTAssertEqual(reopened.supplementalContext?.lastNotice, notice)
        XCTAssertTrue(try XCTUnwrap(reopened.supplementalContext).hasChangesSinceNotice)
        XCTAssertEqual(try count("SELECT revision FROM goal WHERE id = \(goalID)"), notice.goalRevision + 1)
        try reopened.confirmSupplementalContext(text, for: goalID)
        XCTAssertEqual(try count("SELECT revision FROM goal WHERE id = \(goalID)"), notice.goalRevision + 1)
        try reopened.updateSupplementalDraft("편집 중", for: goalID)
        try reopened.startNewGoal()
        XCTAssertNil(reopened.supplementalContext)
        try reopened.selectGoal(goalID)
        let restored = try makeFlow(provider)
        XCTAssertEqual(restored.supplementalContext?.confirmedText, text)
        XCTAssertEqual(restored.supplementalContext?.draftText, "편집 중")
        XCTAssertEqual(restored.supplementalContext?.lastNotice, notice)
        XCTAssertEqual(restored.goalDetails?.statement, "과거 경력 사실 정리")
        let calls = await provider.requests
        XCTAssertEqual(calls.map(\.kind), [.firstAction])
    }

    func testFirstInsufficientInfoEndsNormallyAndRestoresWithoutCallingProvider() async throws {
        let reason = try InsufficientInfoFixture.reason()
        let provider = ScriptedProvider([.insufficientInfo(reason)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "과거 경력 사실 정리")
        await flow.waitForSuggestion()
        XCTAssertNil(flow.screen.suggestionProblem)
        XCTAssertFalse(flow.screen.isWaitingForSuggestion)
        let screen = flow.screen
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        try flow.retrySuggestion()
        XCTAssertEqual(flow.screen, screen)
        try flow.startNewGoal()
        try flow.selectGoal(goalID)
        XCTAssertEqual(flow.screen, screen)
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, screen)
        XCTAssertEqual(reopened.goalDetails?.statement, "과거 경력 사실 정리")
        XCTAssertEqual(reopened.goals.first?.completedActionCount, 0)
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction])
    }

    func testConfirmedNewInformationExplicitlyRequestsFirstActionOnlyOnce() async throws {
        let provider = ScriptedProvider([.insufficientInfo(try InsufficientInfoFixture.reason()), .action(first)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "과거 경력 사실 정리")
        await flow.waitForSuggestion()
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        let notice = try XCTUnwrap(flow.supplementalContext?.lastNotice)
        try flow.updateSupplementalDraft("제가 첫 문단을 작성했어요.", for: goalID)
        try flow.confirmSupplementalContext("제가 첫 문단을 작성했어요.", for: goalID)
        let savedCalls = await provider.requests
        XCTAssertEqual(savedCalls.count, 1)
        try flow.updateSupplementalDraft("아직 확인하지 않은 편집 중 내용", for: goalID)
        try flow.retrySuggestion()
        try flow.retrySuggestion()
        await flow.waitForSuggestion()
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction, .firstAction])
        XCTAssertNotEqual(requests.first?.stateKey, requests.last?.stateKey)
        guard case .currentAction(let card, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, first.task)
        XCTAssertEqual(flow.supplementalContext?.lastNotice, notice)
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, flow.screen)
        XCTAssertEqual(reopened.supplementalContext?.confirmedText, "제가 첫 문단을 작성했어요.")
        XCTAssertEqual(reopened.supplementalContext?.draftText, "아직 확인하지 않은 편집 중 내용")
        XCTAssertEqual(reopened.goals.last?.completedActionCount, 0)
    }

    func testAllReproposalsIgnoresWhitespaceDraftsAndRevertedInformation() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.insufficientInfo("最初の案内"), .insufficientInfo("새 정보를 확인한 안내")])
            let flow = try await beginActionRequest(kind, provider: provider)
            let goalID = try XCTUnwrap(flow.goalDetails?.id)
            for blank in ["", " \r\n\t"] {
                try flow.confirmSupplementalContext(blank, for: goalID)
                XCTAssertFalse(flow.canRequestWithNewInformation)
                try flow.retrySuggestion()
            }
            let text = "제가 첫 문단을 썼어요.\r\n資料を選びました。"
            try flow.confirmSupplementalContext(text, for: goalID)
            XCTAssertTrue(flow.canRequestWithNewInformation)
            try flow.retrySuggestion()
            await flow.waitForSuggestion()
            let notice = try XCTUnwrap(flow.supplementalContext?.lastNotice)
            XCTAssertEqual(notice.reason, "새 정보를 확인한 안내")
            XCTAssertFalse(flow.canRequestWithNewInformation)
            for unchanged in [text, "  제가 첫 문단을 썼어요.\n資料を選びました。  ", "중간에 다른 내용", text] {
                try flow.confirmSupplementalContext(unchanged, for: goalID)
            }
            try flow.updateSupplementalDraft("보내면 안 되는 새 초안", for: goalID)
            XCTAssertFalse(flow.canRequestWithNewInformation)
            try flow.confirmSupplementalContext("  제가 첫 문단을 썼어요.\n資料を選びました。  ", for: goalID)
            XCTAssertFalse(flow.canRequestWithNewInformation)
            try flow.retrySuggestion()
            await flow.waitForSuggestion()
            let requests = await provider.requests
            XCTAssertEqual(requests.count, kind == .firstAction ? 2 : 3)
            XCTAssertEqual(flow.supplementalContext?.lastNotice, notice)
            XCTAssertEqual(flow.supplementalContext?.confirmedText, "  제가 첫 문단을 썼어요.\n資料を選びました。  ")
            XCTAssertFalse(try makeFlow(provider).canRequestWithNewInformation)
        }
    }

    func testAllReproposalsRechecksPendingBeforeCallingProvider() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            for change in ["cancel", "switch", "edit", "confirm", "reopen", "stop"] {
                let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.insufficientInfo("이전 안내"), .action(second)])
                let flow = try await beginActionRequest(kind, provider: provider)
                let goalID = try XCTUnwrap(flow.goalDetails?.id)
                try flow.confirmSupplementalContext("제가 첫 문단을 썼어요.", for: goalID)
                try flow.retrySuggestion()
                switch change {
                case "cancel": try flow.cancelSuggestion()
                case "switch": try flow.startNewGoal()
                case "edit": try flow.editGoalStatement("바뀐 목표 문구")
                case "confirm": try flow.confirmSupplementalContext("두 번째 확인 내용", for: goalID)
                case "reopen": _ = try makeFlow(provider)
                default: try flow.stopGoal()
                }
                await flow.waitForSuggestion()
                let requests = await provider.requests
                XCTAssertEqual(requests.count, kind == .firstAction ? 1 : 2, "\(kind)/\(change)")
                let restored = try makeFlow(provider)
                if restored.goalDetails?.id != goalID { try restored.selectGoal(goalID) }
                XCTAssertEqual(restored.supplementalContext?.confirmedText, change == "confirm" ? "두 번째 확인 내용" : "제가 첫 문단을 썼어요.")
                XCTAssertFalse(restored.canRequestWithNewInformation)
                XCTAssertEqual(restored.supplementalContext?.lastNotice?.reason, "이전 안내")
            }
        }
    }

    func testAllReproposalsLateResultsNeverOverrideChangedOrInterruptedProgress() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            for change in ["cancel", "switch", "edit", "confirm", "reopen", "stop", "draft"] {
                let initial = try await beginActionRequest(kind, provider: ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.insufficientInfo("이전 안내")]))
                let goalID = try XCTUnwrap(initial.goalDetails?.id)
                try initial.confirmSupplementalContext("제가 첫 문단을 썼어요.", for: goalID)
                let provider = HeldProvider(.action(second))
                let flow = try makeFlow(provider)
                try flow.updateSupplementalDraft("남겨둘 초안", for: goalID)
                try flow.retrySuggestion()
                for _ in 0..<10_000 where await provider.requests == 0 { await Task.yield() }
                let started = await provider.requests
                XCTAssertEqual(started, 1)
                try flow.retrySuggestion()
                switch change {
                case "cancel": try flow.cancelSuggestion()
                case "switch": try flow.startNewGoal()
                case "edit": try flow.editGoalStatement("바뀐 목표 문구")
                case "confirm": try flow.confirmSupplementalContext("두 번째 확인 내용", for: goalID)
                case "reopen": _ = try makeFlow(provider)
                case "stop": try flow.stopGoal()
                default: try flow.updateSupplementalDraft("요청 중 바꾼 초안", for: goalID)
                }
                await provider.release()
                await flow.waitForSuggestion()
                let restored = try makeFlow(provider)
                if restored.goalDetails?.id != goalID { try restored.selectGoal(goalID) }
                if change == "draft" {
                    guard case .currentAction(let card, nil) = restored.screen else { return XCTFail("\(restored.screen)") }
                    XCTAssertEqual(card.task, second.task)
                } else if case .currentAction(let card, _) = restored.screen { XCTAssertNotEqual(card.task, second.task, "\(kind)/\(change)") }
                XCTAssertEqual(restored.supplementalContext?.confirmedText, change == "confirm" ? "두 번째 확인 내용" : "제가 첫 문단을 썼어요.")
                XCTAssertEqual(restored.supplementalContext?.draftText, change == "confirm" ? nil : change == "draft" ? "요청 중 바꾼 초안" : "남겨둘 초안")
                XCTAssertEqual(restored.supplementalContext?.lastNotice?.reason, "이전 안내")
                XCTAssertEqual(restored.goals.last?.completedActionCount, kind == .nextAction ? 1 : 0)
                let calls = await provider.requests
                XCTAssertEqual(calls, 1)
            }
        }
    }

    func testAllReproposalsOversizedInputPreservesConfirmedTextDraftAndNotice() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.insufficientInfo("이전 안내"), .action(second)])
            let flow = try await beginActionRequest(kind, provider: provider)
            let goalID = try XCTUnwrap(flow.goalDetails?.id)
            let notice = flow.supplementalContext?.lastNotice
            let oversized = String(repeating: "가", count: 10_922)
            try flow.confirmSupplementalContext(oversized, for: goalID)
            try flow.updateSupplementalDraft("수정 중인 초안", for: goalID)
            let before = flow.screen
            XCTAssertThrowsError(try flow.retrySuggestion()) { error in
                guard case ProgressFlowError.supplementalRequestTooLarge = error else { return XCTFail("\(error)") }
            }
            XCTAssertEqual(flow.screen, before)
            let reopened = try makeFlow(provider)
            XCTAssertEqual(reopened.screen, before)
            XCTAssertEqual(reopened.supplementalContext?.confirmedText, oversized)
            XCTAssertEqual(reopened.supplementalContext?.draftText, "수정 중인 초안")
            XCTAssertEqual(reopened.supplementalContext?.lastNotice, notice)
            let unchanged = await provider.requests
            XCTAssertEqual(unchanged.count, kind == .firstAction ? 1 : 2)
            try reopened.confirmSupplementalContext("제가 첫 문단을 썼어요.", for: goalID)
            try reopened.retrySuggestion()
            await reopened.waitForSuggestion()
            guard case .currentAction = reopened.screen else { return XCTFail("\(reopened.screen)") }
            let sent = await provider.requests
            XCTAssertEqual(sent.count, kind == .firstAction ? 2 : 3)
        }
    }

    func testFirstReproposalFailureKeepsNoticeAndRequiresSeparateManualRetry() async throws {
        let provider = ScriptedProvider([.success(.insufficientInfo("이전 안내")), .failure(.connectionLost), .success(.insufficientInfo("새 안내"))])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "경력 사실 정리")
        await flow.waitForSuggestion()
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        let notice = flow.supplementalContext?.lastNotice
        try flow.confirmSupplementalContext("제가 첫 문단을 썼어요.", for: goalID)
        try flow.updateSupplementalDraft("남겨둘 편집 초안", for: goalID)
        try flow.retrySuggestion()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen.suggestionProblem, .failure(.connectionLost))
        XCTAssertEqual(flow.supplementalContext?.lastNotice, notice)
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, flow.screen)
        XCTAssertEqual(reopened.supplementalContext?.draftText, "남겨둘 편집 초안")
        XCTAssertFalse(reopened.canRequestWithNewInformation)
        let failed = await provider.requests
        XCTAssertEqual(failed.count, 2)
        try reopened.retrySuggestion()
        try reopened.retrySuggestion()
        await reopened.waitForSuggestion()
        guard case .insufficientInfo(let latest, false) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(latest.reason, "새 안내")
        XCTAssertNotEqual(latest.requestID, notice?.requestID)
        XCTAssertFalse(reopened.canRequestWithNewInformation)
        try reopened.retrySuggestion()
        let requests = await provider.requests
        XCTAssertEqual(requests.count, 3)
        XCTAssertEqual(requests[1].supplementalText, requests[2].supplementalText)
    }

    func testHTTPFirstReproposalSendsOnlyConfirmedSelectedGoalInformation() async throws {
        let shared = try InsufficientInfoFixture.json()
        let scenario = shared["supplemental_first_action"] as! [String: Any]
        let confirmed = scenario["confirmed_text"] as! String
        let draft = scenario["draft_text"] as! String
        for server in [false, true] {
            DevelopmentTransport.store.reset()
            DevelopmentTransport.store.handler = { http in
                let payload = try JSONSerialization.jsonObject(with: http.httpBody!) as! [String: Any]
                let input = payload["input"] as! [String: Any]
                let hasConfirmed = (input["available"] as! [String]).contains(scenario["available_fact"] as! String)
                var response = (hasConfirmed ? scenario["response"] : shared["response"]) as! [String: Any]
                var proposal = response["proposal"] as! [String: Any]
                proposal["remaining_work"] = input["remaining_work"]
                proposal["preserved_completed_ids"] = input["completed_ids"]
                response["proposal"] = proposal
                return (200, try JSONSerialization.data(withJSONObject: response))
            }
            let configuration = URLSessionConfiguration.ephemeral
            configuration.protocolClasses = [DevelopmentTransport.self]
            let session = URLSession(configuration: configuration)
            let provider = server
                ? HTTPActionSuggestionProvider.server(baseURL: URL(string: "https://api.example.invalid")!, token: { "test-identity" }, session: session)
                : HTTPActionSuggestionProvider.development(baseURL: URL(string: "http://127.0.0.1:8080")!, token: nil, session: session)
            let flow = try makeFlow(provider)
            try await startGoal(flow, "다른 목표")
            await flow.waitForSuggestion()
            guard case .insufficientInfo = flow.screen else { return XCTFail("\(flow.screen)") }
            try flow.confirmSupplementalContext("다른 목표의 보내면 안 되는 내용", for: XCTUnwrap(flow.goalDetails?.id))
            try flow.startNewGoal()
            let input = shared["input"] as! [String: Any]
            try flow.updateGoalInput(GoalInput(statement: input["goal"] as! String, currentState: "확인 가능한 자료와 추가로 답할 내용이 없어요.", blocker: input["current_blocker"] as! String))
            try flow.prepareGoal()
            await flow.waitForSuggestion()
            try flow.confirmGoal(completionCriteria: input["goal"] as! String)
            await flow.waitForSuggestion()
            let goalID = try XCTUnwrap(flow.goalDetails?.id)
            try flow.confirmSupplementalContext(confirmed, for: goalID)
            try flow.updateSupplementalDraft(draft, for: goalID)
            let reopened = try makeFlow(provider)
            XCTAssertEqual(DevelopmentTransport.store.requests.count, 2)
            try reopened.retrySuggestion()
            try reopened.retrySuggestion()
            await reopened.waitForSuggestion()
            XCTAssertEqual(DevelopmentTransport.store.requests.count, 3)
            let sent = try XCTUnwrap(DevelopmentTransport.store.requests.last)
            XCTAssertEqual(sent.url?.path, server ? "/v1/suggestions" : "/development/suggestions")
            let payload = try JSONSerialization.jsonObject(with: sent.httpBody!) as! [String: Any]
            var expected = input
            expected["available"] = (input["available"] as! [String]) + [scenario["available_fact"] as! String]
            XCTAssertEqual(payload["input"] as? NSDictionary, expected as NSDictionary)
            guard case .currentAction(let card, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
            let response = scenario["response"] as! [String: Any]
            XCTAssertEqual(card.task, (response["proposal"] as! [String: Any])["action"] as? String)
            XCTAssertEqual(reopened.supplementalContext?.confirmedText, confirmed)
            XCTAssertEqual(reopened.supplementalContext?.draftText, draft)
        }
    }

    func testSupplementalReproposalResumesOriginalKindWithoutRepeatingProgress() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.insufficientInfo("이전 안내"), .action(second)])
            let flow = try await beginActionRequest(kind, provider: provider)
            let goalID = try XCTUnwrap(flow.goalDetails?.id)
            let notice = try XCTUnwrap(flow.supplementalContext?.lastNotice)
            try flow.confirmSupplementalContext("제가 첫 문단을 썼어요.", for: goalID)
            let reopened = try makeFlow(provider)
            XCTAssertTrue(reopened.canRequestWithNewInformation, "\(kind)")
            let saved = await provider.requests
            XCTAssertEqual(saved.count, kind == .firstAction ? 1 : 2)
            try reopened.retrySuggestion()
            try reopened.retrySuggestion()
            await reopened.waitForSuggestion()
            let requests = await provider.requests
            XCTAssertEqual(requests.map(\.kind), (kind == .firstAction ? [] : [.firstAction]) + [kind, kind])
            XCTAssertEqual(requests.last?.supplementalText, "제가 첫 문단을 썼어요.")
            XCTAssertEqual(requests.last?.completedActionIDs, requests.dropLast().last?.completedActionIDs)
            XCTAssertEqual(requests.last?.deferredTasks, kind == .replacement ? [first.task] : [])
            guard case .currentAction(let card, nil) = reopened.screen else { return XCTFail("\(kind): \(reopened.screen)") }
            XCTAssertEqual(card.task, second.task)
            XCTAssertEqual(card.origin?.task, kind == .smaller ? first.task : nil)
            XCTAssertEqual(reopened.supplementalContext?.lastNotice, notice)
            XCTAssertEqual(try makeFlow(provider).screen, reopened.screen)
            XCTAssertEqual(reopened.goals.last?.completedActionCount, kind == .nextAction ? 1 : 0)
        }
    }

    func testSupplementalReproposalCannotStartForStoppedGoal() async throws {
        let provider = ScriptedProvider([.insufficientInfo("이전 안내")])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "새 경력 사실 정리")
        await flow.waitForSuggestion()
        try flow.confirmSupplementalContext("제가 첫 문단을 썼어요.", for: XCTUnwrap(flow.goalDetails?.id))
        try flow.stopGoal()
        XCTAssertFalse(flow.canRequestWithNewInformation)
        try flow.retrySuggestion()
        let requests = await provider.requests
        XCTAssertEqual(requests.count, 1)
    }

    func testFirstReproposalStorageFailurePreservesEditableInputWithoutCallingProvider() async throws {
        let provider = ScriptedProvider([.insufficientInfo("이전 안내"), .action(first)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "경력 사실 정리")
        await flow.waitForSuggestion()
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        try flow.confirmSupplementalContext("제가 첫 문단을 썼어요.", for: goalID)
        try flow.updateSupplementalDraft("남겨둘 초안", for: goalID)
        let before = flow.screen
        let database = try AppDatabase(path: path)
        try await database.writer.write { try $0.execute(sql: "CREATE TRIGGER reject_reproposal BEFORE INSERT ON suggestion_request BEGIN SELECT RAISE(ABORT, 'test failure'); END") }
        XCTAssertThrowsError(try flow.retrySuggestion())
        XCTAssertEqual(flow.screen, before)
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, before)
        XCTAssertEqual(reopened.supplementalContext?.confirmedText, "제가 첫 문단을 썼어요.")
        XCTAssertEqual(reopened.supplementalContext?.draftText, "남겨둘 초안")
        XCTAssertTrue(reopened.canRequestWithNewInformation)
        let requests = await provider.requests
        XCTAssertEqual(requests.count, 1)
        try await database.writer.write { try $0.execute(sql: "DROP TRIGGER reject_reproposal") }
        try reopened.retrySuggestion()
        await reopened.waitForSuggestion()
        guard case .currentAction = reopened.screen else { return XCTFail("\(reopened.screen)") }
    }

    func testStaleFirstReproposalCannotCreateAnotherActionAfterProgressChanged() async throws {
        let provider = ScriptedProvider([.insufficientInfo("이전 안내"), .action(first)])
        let stale = try makeFlow(provider)
        try await startGoal(stale, "경력 사실 정리")
        await stale.waitForSuggestion()
        try stale.confirmSupplementalContext("제가 첫 문단을 썼어요.", for: XCTUnwrap(stale.goalDetails?.id))
        let active = try makeFlow(provider)
        try active.retrySuggestion()
        await active.waitForSuggestion()
        let expected = active.screen
        XCTAssertFalse(stale.canRequestWithNewInformation)
        try stale.retrySuggestion()
        XCTAssertEqual(stale.screen, expected)
        let requests = await provider.requests
        XCTAssertEqual(requests.count, 2)
    }

    func testHTTPNewInformationPreservesOriginalQuestionsBlockerAndProgressOnBothAdapters() async throws {
        let shared = try InsufficientInfoFixture.json()
        let scenario = shared["supplemental_first_action"] as! [String: Any]
        let confirmed = scenario["confirmed_text"] as! String
        let question = shared["question"] as! String
        let answer = shared["answer"] as! String
        for server in [false, true] {
            for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
                for mode in ["action", "insufficient_info", "need_info", "no_action", "connection", "format", "rejected", "uncertain"] where mode != "no_action" || kind == .replacement {
                    DevelopmentTransport.store.reset()
                    DevelopmentTransport.store.handler = { http in
                        let payload = try JSONSerialization.jsonObject(with: http.httpBody!) as! [String: Any]
                        let input = payload["input"] as! [String: Any]
                        let available = input["available"] as! [String]
                        let target = input["request_kind"] as! String == kind.rawValue
                        let answered = available.contains("행동 요청에서 이미 답한 질문: \(question) / 답: \(answer)")
                        let supplemented = available.contains(scenario["available_fact"] as! String)
                        if supplemented && target {
                            if mode == "connection" { throw URLError(.networkConnectionLost) }
                            if mode == "format" { return (200, Data("{}".utf8)) }
                            if mode == "rejected" || mode == "uncertain" {
                                return (200, try JSONSerialization.data(withJSONObject: ["disposition": mode]))
                            }
                        }
                        var response = (supplemented ? scenario["response"] : shared["response"]) as! [String: Any]
                        var proposal = response["proposal"] as! [String: Any]
                        let status = !target ? "action" : !answered ? "need_info" : supplemented ? mode : "insufficient_info"
                        proposal["status"] = status
                        switch status {
                        case "action":
                            if !target {
                                proposal["action"] = self.first.task
                                proposal["completion_condition"] = self.first.doneWhen
                                proposal["estimated_minutes"] = self.first.estimatedMinutes
                            }
                        case "need_info":
                            proposal["action"] = answered ? shared["supplemental_question"] as! String : question
                            proposal["completion_condition"] = "알고 있는 답을 전한다"
                            proposal["estimated_minutes"] = 0
                        case "no_action": break
                        default:
                            proposal["action"] = ""
                            proposal["completion_condition"] = ""
                            proposal["estimated_minutes"] = 0
                        }
                        proposal["remaining_work"] = input["remaining_work"]
                        proposal["preserved_completed_ids"] = input["completed_ids"]
                        response["proposal"] = proposal
                        return (200, try JSONSerialization.data(withJSONObject: response))
                    }
                    let config = URLSessionConfiguration.ephemeral
                    config.protocolClasses = [DevelopmentTransport.self]
                    let session = URLSession(configuration: config)
                    let provider = server
                        ? HTTPActionSuggestionProvider.server(baseURL: URL(string: "https://api.example.invalid")!, token: { "test-identity" }, session: session)
                        : HTTPActionSuggestionProvider.development(baseURL: URL(string: "http://127.0.0.1:8080")!, token: nil, session: session)
                    let flow = try await beginActionRequest(kind, provider: provider)
                    try flow.answerQuestion(answer)
                    await flow.waitForSuggestion()
                    let goalID = try XCTUnwrap(flow.goalDetails?.id)
                    let notice = try XCTUnwrap(flow.supplementalContext?.lastNotice)
                    let before = DevelopmentTransport.store.requests.count
                    try flow.confirmSupplementalContext(confirmed, for: goalID)
                    try flow.updateSupplementalDraft("전송하지 않는 초안", for: goalID)
                    let reopened = try makeFlow(provider)
                    XCTAssertEqual(DevelopmentTransport.store.requests.count, before)
                    try reopened.retrySuggestion()
                    try reopened.retrySuggestion()
                    await reopened.waitForSuggestion()
                    XCTAssertEqual(DevelopmentTransport.store.requests.count, before + 1, "\(server)/\(kind)/\(mode)")
                    let requests = DevelopmentTransport.store.requests
                    let oldPayload = try JSONSerialization.jsonObject(with: requests[before - 1].httpBody!) as! [String: Any]
                    let oldInput = oldPayload["input"] as! [String: Any]
                    let payload = try JSONSerialization.jsonObject(with: requests.last!.httpBody!) as! [String: Any]
                    let input = payload["input"] as! [String: Any]
                    XCTAssertEqual(input["request_kind"] as? String, kind.rawValue)
                    XCTAssertEqual(input["current_blocker"] as? String, kind == .smaller ? answer : "")
                    let available = input["available"] as! [String]
                    XCTAssertTrue(available.contains(scenario["available_fact"] as! String))
                    XCTAssertEqual(available.filter { $0 != scenario["available_fact"] as! String }, oldInput["available"] as! [String])
                    XCTAssertEqual(input["remaining_work"] as? [String], oldInput["remaining_work"] as? [String])
                    XCTAssertEqual(input["completed_ids"] as? [String], oldInput["completed_ids"] as? [String])
                    XCTAssertEqual(try JSONSerialization.data(withJSONObject: input["previous_proposals"]!, options: .sortedKeys),
                                   try JSONSerialization.data(withJSONObject: oldInput["previous_proposals"]!, options: .sortedKeys))
                    XCTAssertEqual(reopened.supplementalContext?.confirmedText, confirmed)
                    XCTAssertEqual(reopened.supplementalContext?.draftText, "전송하지 않는 초안")
                    switch mode {
                    case "action":
                        guard case .currentAction(let card, nil) = reopened.screen else { return XCTFail("\(kind): \(reopened.screen)") }
                        XCTAssertEqual(card.task, ((scenario["response"] as! [String: Any])["proposal"] as! [String: Any])["action"] as? String)
                    case "insufficient_info":
                        guard case .insufficientInfo(let latest, false) = reopened.screen else { return XCTFail("\(reopened.screen)") }
                        XCTAssertNotEqual(latest.requestID, notice.requestID)
                        XCTAssertFalse(reopened.canRequestWithNewInformation)
                    case "need_info":
                        XCTAssertNotNil(reopened.suggestionInput)
                    case "no_action":
                        guard case .onHold(let deferred, .noAction) = reopened.screen else { return XCTFail("\(reopened.screen)") }
                        XCTAssertEqual(deferred.map(\.task), [first.task])
                    default:
                        let problem: SuggestionProblem
                        if case .currentAction(_, .problem(let value)) = reopened.screen { problem = value }
                        else { problem = try XCTUnwrap(reopened.screen.suggestionProblem) }
                        XCTAssertEqual(problem, .failure(mode == "connection" ? .connectionLost : mode == "rejected" ? .rejected : mode == "uncertain" ? .undecidable : .failed))
                        XCTAssertEqual(reopened.supplementalContext?.lastNotice, notice)
                    }
                    XCTAssertEqual(try makeFlow(provider).screen, reopened.screen)
                    XCTAssertEqual(reopened.goals.last?.completedActionCount, kind == .nextAction ? 1 : 0)
                }
            }
        }
    }

    func testStaleNoticeCannotRequestAnotherSelectedGoalsNewInformation() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.insufficientInfo("목표 A 안내"), .insufficientInfo("목표 B 안내"), .action(second)])
            let stale = try await beginActionRequest(kind, provider: provider)
            let originalID = try XCTUnwrap(stale.goalDetails?.id)
            try stale.confirmSupplementalContext("목표 A 확인값", for: originalID)
            let selected = try await beginActionRequest(.firstAction, provider: provider)
            let selectedID = try XCTUnwrap(selected.goalDetails?.id)
            XCTAssertNotEqual(originalID, selectedID)
            try selected.confirmSupplementalContext("목표 B 확인값", for: selectedID)
            let expected = selected.screen
            XCTAssertFalse(stale.canRequestWithNewInformation)
            try stale.retrySuggestion()
            await stale.waitForSuggestion()
            let requests = await provider.requests
            XCTAssertEqual(requests.count, kind == .firstAction ? 2 : 3)
            let reopened = try makeFlow(provider)
            XCTAssertEqual(reopened.screen, expected)
            XCTAssertEqual(reopened.goalDetails?.id, selectedID)
            XCTAssertEqual(reopened.supplementalContext?.confirmedText, "목표 B 확인값")
            try reopened.selectGoal(originalID)
            XCTAssertEqual(reopened.supplementalContext?.confirmedText, "목표 A 확인값")
            XCTAssertEqual(reopened.goals.first { $0.id == originalID }?.completedActionCount, kind == .nextAction ? 1 : 0)
        }
    }

    func testSmallerNoticeCannotRetryAfterUndoChangesItsCurrentAction() async throws {
        let provider = ScriptedProvider([.action(first), .action(second), .insufficientInfo("이전 안내")])
        let flow = try await beginActionRequest(.smaller, provider: provider)
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        try flow.confirmSupplementalContext("새로 확인한 사실", for: XCTUnwrap(flow.goalDetails?.id))
        let stale = try makeFlow(provider)
        try flow.dismissInformationNotice()
        try flow.undoSplit()
        XCTAssertFalse(stale.canRequestWithNewInformation)
        try stale.retrySuggestion()
        let requests = await provider.requests
        XCTAssertEqual(requests.count, 3)
        XCTAssertEqual(stale.supplementalContext?.confirmedText, "새로 확인한 사실")
        XCTAssertEqual(stale.goals.last?.completedActionCount, 0)
    }

    private func beginActionRequest(_ kind: SuggestionKind, provider: any ActionSuggestionProvider) async throws -> ProgressFlow {
        let flow = try makeFlow(provider)
        try await startGoal(flow, "과거 경력 사실 정리")
        if kind != .firstAction {
            await flow.waitForSuggestion()
            switch kind {
            case .smaller: try flow.makeSmaller()
            case .nextAction: try flow.complete()
            case .replacement: try flow.deferAction()
            default: XCTFail("행동 요청만 사용한다")
            }
        }
        await flow.waitForSuggestion()
        return flow
    }

    func testFollowupNoticesRestoreWithoutRepeatingCompletionOrDeferral() async throws {
        for kind in [SuggestionKind.smaller, .nextAction, .replacement] {
            let provider = ScriptedProvider([.action(first), .insufficientInfo(try InsufficientInfoFixture.reason())])
            let flow = try await beginActionRequest(kind, provider: provider)
            guard case .insufficientInfo(let notice, false) = flow.screen else { return XCTFail("\(kind): \(flow.screen)") }
            XCTAssertEqual(notice.requestKind, kind)
            let goalID = try XCTUnwrap(flow.goalDetails?.id)
            let expectedCompleted = kind == .nextAction ? 1 : 0
            XCTAssertEqual(flow.goals.last?.completedActionCount, expectedCompleted)
            let original = flow.screen
            try flow.retrySuggestion()
            try flow.startNewGoal()
            try flow.selectGoal(goalID)
            XCTAssertEqual(flow.screen, original)
            XCTAssertEqual(try makeFlow(provider).screen, original)
            let requests = await provider.requests
            XCTAssertEqual(requests.map(\.kind), [.firstAction, kind])
            XCTAssertEqual(requests.last?.remainingTasks, kind == .nextAction ? [] : [first.task])
            XCTAssertEqual(requests.last?.completedActionIDs.count, expectedCompleted)
            XCTAssertEqual(requests.last?.deferredTasks, kind == .replacement ? [first.task] : [])
        }
    }

    func testActionQuestionsRestoreDraftAndSubmitOnceWithOriginalKind() async throws {
        let shared = try InsufficientInfoFixture.json()
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            let question = shared["question"] as! String
            let answer = shared["answer"] as! String
            let outcomes: [SuggestionCandidate] = (kind == .firstAction ? [] : [.action(first)])
                + [.question(question), .insufficientInfo(try InsufficientInfoFixture.reason())]
            let provider = ScriptedProvider(outcomes)
            let flow = try await beginActionRequest(kind, provider: provider)
            let input = try XCTUnwrap(flow.suggestionInput, "\(kind): \(flow.screen)")
            let questionScreen = flow.screen
            let goalID = try XCTUnwrap(flow.goalDetails?.id)
            try flow.updateSuggestionInput(answer, for: input.requestID)
            try flow.startNewGoal()
            try flow.selectGoal(goalID)
            XCTAssertEqual(flow.screen, questionScreen)
            let reopened = try makeFlow(provider)
            XCTAssertEqual(reopened.suggestionInput?.text, answer)
            XCTAssertEqual(reopened.suggestionInput?.requestID, input.requestID)
            XCTAssertThrowsError(try reopened.answerQuestion(" \n"))
            try reopened.answerQuestion(answer)
            try reopened.answerQuestion(answer)
            XCTAssertThrowsError(try reopened.updateSuggestionInput("늦은 입력", for: input.requestID))
            await reopened.waitForSuggestion()
            guard case .insufficientInfo(let notice, false) = reopened.screen else { return XCTFail("\(kind): \(reopened.screen)") }
            XCTAssertEqual(notice.requestKind, kind)
            let requests = await provider.requests
            XCTAssertEqual(requests.map(\.kind), (kind == .firstAction ? [] : [.firstAction]) + [kind, kind])
            XCTAssertEqual(requests.last?.blocker, kind == .smaller ? answer : nil)
            XCTAssertEqual(requests.last?.context.answers, [])
            XCTAssertEqual(requests.last?.actionAnswers, [GoalAnswer(question: question, answer: answer)])
            XCTAssertEqual(requests.last?.completedActionIDs.count, kind == .nextAction ? 1 : 0)
            XCTAssertEqual(requests.last?.deferredTasks, kind == .replacement ? [first.task] : [])
        }
    }

    func testSmallerNoticeReturnsToPreservedActionAndKeepsDraftThroughCommands() async throws {
        let provider = ScriptedProvider([.action(first), .insufficientInfo(try InsufficientInfoFixture.reason()), .action(second)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "경력 정리")
        await flow.waitForSuggestion()
        guard case .currentAction(let card, _) = flow.screen else { return XCTFail() }
        try flow.recordResult("자료 미기재를 확인함", for: card.id)
        try flow.updateDraft("기억나는 내용 초안", for: card.id)
        let original = flow.screen
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        let notice = flow.screen
        try flow.dismissInformationNotice()
        XCTAssertEqual(flow.screen, original)
        try flow.updateDraft("바꾼 초안", for: card.id)
        guard case .currentAction(let restored, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(restored.results.map(\.body), ["자료 미기재를 확인함"])
        XCTAssertEqual(restored.draft, "바꾼 초안")
        XCTAssertEqual(try makeFlow(provider).screen, notice)
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        try flow.startNewGoal()
        try flow.selectGoal(goalID)
        XCTAssertEqual(flow.screen, notice)
        try flow.dismissInformationNotice()
        try flow.complete()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.goals.last?.completedActionCount, 1)
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction, .smaller, .nextAction])
    }

    func testHTTPQuestionsSendConfirmedAnswersWithOriginalScopeOnBothAdapters() async throws {
        let shared = try InsufficientInfoFixture.json()
        let question = shared["question"] as! String
        let answer = shared["answer"] as! String
        for server in [false, true] {
            for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
                DevelopmentTransport.store.reset()
                DevelopmentTransport.store.handler = { http in
                    let payload = try JSONSerialization.jsonObject(with: http.httpBody!) as! [String: Any]
                    let input = payload["input"] as! [String: Any]
                    let answered = (input["available"] as! [String]).contains("행동 요청에서 이미 답한 질문: \(question) / 답: \(answer)")
                    let requested = input["request_kind"] as! String == kind.rawValue
                    var proposal = shared["response"] as! [String: Any]
                    var value = proposal["proposal"] as! [String: Any]
                    if !requested || !answered {
                        value["status"] = requested ? "need_info" : "action"
                        value["action"] = requested ? question : "관련 메모 하나 열기"
                        value["completion_condition"] = requested ? "알고 있는 답을 전한다" : "메모가 화면에 열려 있다"
                        value["estimated_minutes"] = requested ? 0 : 3
                    }
                    value["remaining_work"] = input["remaining_work"]
                    value["preserved_completed_ids"] = input["completed_ids"]
                    proposal["proposal"] = value
                    return (200, try JSONSerialization.data(withJSONObject: proposal))
                }
                let configuration = URLSessionConfiguration.ephemeral
                configuration.protocolClasses = [DevelopmentTransport.self]
                let session = URLSession(configuration: configuration)
                let provider = server
                    ? HTTPActionSuggestionProvider.server(baseURL: URL(string: "https://api.example.invalid")!, token: { "test-identity" }, session: session)
                    : HTTPActionSuggestionProvider.development(baseURL: URL(string: "http://127.0.0.1:8080")!, token: nil, session: session)
                let flow = try await beginActionRequest(kind, provider: provider)
                let draft = try XCTUnwrap(flow.suggestionInput)
                try flow.updateSuggestionInput(answer, for: draft.requestID)
                XCTAssertEqual(DevelopmentTransport.store.requests.count, kind == .firstAction ? 1 : 2)
                try flow.answerQuestion(answer)
                try flow.answerQuestion(answer)
                await flow.waitForSuggestion()
                guard case .insufficientInfo(let notice, false) = flow.screen else { return XCTFail("\(server)/\(kind): \(flow.screen)") }
                XCTAssertEqual(notice.requestKind, kind)
                let requests = DevelopmentTransport.store.requests
                XCTAssertEqual(requests.count, kind == .firstAction ? 2 : 3)
                XCTAssertEqual(requests.last?.url?.path, server ? "/v1/suggestions" : "/development/suggestions")
                let payload = try JSONSerialization.jsonObject(with: requests.last!.httpBody!) as! [String: Any]
                let input = payload["input"] as! [String: Any]
                XCTAssertEqual(input["request_kind"] as? String, kind.rawValue)
                XCTAssertEqual(input["current_blocker"] as? String, kind == .smaller ? answer : "")
                XCTAssertEqual((input["completed_ids"] as! [String]).count, kind == .nextAction ? 1 : 0)
                XCTAssertEqual(input["remaining_work"] as? [String], ["과거 경력 사실 정리"] + (kind == .nextAction || kind == .firstAction ? [] : [first.task]))
            }
        }
    }

    func testOversizedActionAnswerKeepsQuestionDraftAndAllowsCorrection() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.question("기록이 있나요?"), .action(second)])
            let flow = try await beginActionRequest(kind, provider: provider)
            let original = flow.screen
            let input = try XCTUnwrap(flow.suggestionInput)
            let text = String(repeating: "가", count: kind == .smaller ? 700 : 11_000)
            try flow.updateSuggestionInput(text, for: input.requestID)
            XCTAssertThrowsError(try flow.answerQuestion(text))
            XCTAssertEqual(flow.screen, original)
            let reopened = try makeFlow(provider)
            XCTAssertEqual(reopened.screen, original)
            XCTAssertEqual(reopened.suggestionInput?.text, text)
            let before = await provider.requests
            XCTAssertEqual(before.count, kind == .firstAction ? 1 : 2)
            try reopened.answerQuestion("기억나지 않고 자료도 없어요")
            await reopened.waitForSuggestion()
            guard case .currentAction(let action, nil) = reopened.screen else { return XCTFail("\(kind): \(reopened.screen)") }
            XCTAssertEqual(action.task, second.task)
            let after = await provider.requests
            XCTAssertEqual(after.last?.actionAnswers.map(\.answer), ["기억나지 않고 자료도 없어요"])
        }
    }

    func testAnsweredQuestionsCannotRepeatOrBecomeOtherKindsOfAnswers() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            let question = "어느 자료를 확인할 수 있나요?"
            let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.question(question), .question(" \(question) ")])
            let flow = try await beginActionRequest(kind, provider: provider)
            try flow.answerQuestion("확인할 자료가 없어요")
            await flow.waitForSuggestion()
            if case .currentAction(_, .problem(.unsuitable)) = flow.screen { }
            else { XCTAssertEqual(flow.screen.suggestionProblem, .unsuitable, "\(kind): \(flow.screen)") }
            XCTAssertNil(flow.suggestionInput)
            let calls = await provider.requests
            XCTAssertEqual(calls.count, kind == .firstAction ? 2 : 3)
        }
    }

    func testConfirmedSupplementalChangeInvalidatesUnansweredQuestionsWithoutCallingAgain() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.question("기록이 있나요?")])
            let flow = try await beginActionRequest(kind, provider: provider)
            let input = try XCTUnwrap(flow.suggestionInput)
            try flow.updateSuggestionInput("작성 중인 답", for: input.requestID)
            try flow.confirmSupplementalContext("새로 확인한 사용자 진술", for: XCTUnwrap(flow.goalDetails?.id))
            XCTAssertNil(flow.suggestionInput)
            if kind == .smaller {
                guard case .currentAction(_, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
            } else {
                XCTAssertEqual(flow.screen.suggestionProblem, .interrupted, "\(kind): \(flow.screen)")
            }
            XCTAssertEqual(try makeFlow(provider).screen, flow.screen)
            XCTAssertEqual(flow.supplementalContext?.confirmedText, "새로 확인한 사용자 진술")
            let calls = await provider.requests
            XCTAssertEqual(calls.count, kind == .firstAction ? 1 : 2)
        }
    }

    func testPendingQuestionAnswerNeverReplaysOrAppliesAfterLeavingItsState() async throws {
        for kind in [SuggestionKind.firstAction, .smaller, .nextAction, .replacement] {
            for event in ["cancel", "switch", "edit", "reopen", "stop"] {
                let question = "확인할 자료가 있나요?"
                let provider = ScriptedProvider((kind == .firstAction ? [] : [.action(first)]) + [.question(question)])
                _ = try await beginActionRequest(kind, provider: provider)
                let held = HeldProvider(.action(second))
                let flow = try makeFlow(held)
                try flow.answerQuestion("모르고 자료도 없어요")
                try flow.answerQuestion("중복 답")
                switch event {
                case "cancel": try flow.cancelSuggestion()
                case "switch": try flow.startNewGoal()
                case "edit": try flow.editGoalStatement("다른 경력 정리")
                case "reopen": _ = try makeFlow(UnavailableSuggestionProvider())
                default: try flow.stopGoal()
                }
                await held.release()
                await flow.waitForSuggestion()
                if case .currentAction(let card, _) = flow.screen { XCTAssertNotEqual(card.task, second.task) }
                let reopened = try makeFlow(provider)
                if case .currentAction(let card, _) = reopened.screen { XCTAssertNotEqual(card.task, second.task) }
                let calls = await held.requests
                XCTAssertEqual(calls, 1, "\(kind)/\(event)")
            }
        }
    }

    func testSupplementalByteLimitAndStorageFailuresKeepSavedValuesAndPreventNavigation() async throws {
        let provider = ScriptedProvider([.insufficientInfo(try InsufficientInfoFixture.reason())])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "크기와 저장 실패")
        await flow.waitForSuggestion()
        let goalID = try XCTUnwrap(flow.goalDetails?.id)
        let boundary = String(repeating: "😀", count: 8192)
        try flow.confirmSupplementalContext(boundary, for: goalID)
        try flow.updateSupplementalDraft("이전 초안", for: goalID)
        let saved = flow.supplementalContext
        let screen = flow.screen
        let revision = try count("SELECT revision FROM goal WHERE id = \(goalID)")
        let oversized = boundary + "가"
        XCTAssertThrowsError(try flow.updateSupplementalDraft(oversized, for: goalID))
        XCTAssertThrowsError(try flow.confirmSupplementalContext(oversized, for: goalID))
        XCTAssertThrowsError(try flow.run(saving: Drafts(supplementalText: oversized)) { try flow.startNewGoal() })
        XCTAssertEqual(flow.goalDetails?.id, goalID)
        XCTAssertEqual(flow.supplementalContext, saved)
        XCTAssertEqual(flow.screen, screen)
        let database = try AppDatabase(path: path)
        try await database.writer.write { db in
            try db.execute(sql: "CREATE TRIGGER reject_supplemental_save BEFORE UPDATE ON app_metadata WHEN OLD.key = 'supplemental_context:\(goalID)' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        }
        XCTAssertThrowsError(try flow.confirmSupplementalContext("수정한 확인값", for: goalID))
        XCTAssertThrowsError(try flow.run(saving: Drafts(supplementalText: "현재 편집 내용")) { try flow.startNewGoal() })
        XCTAssertEqual(flow.supplementalContext, saved)
        XCTAssertEqual(try makeFlow(provider).supplementalContext, saved)
        XCTAssertEqual(try count("SELECT revision FROM goal WHERE id = \(goalID)"), revision)
        try await database.writer.write { try $0.execute(sql: "DROP TRIGGER reject_supplemental_save") }
        var lock: OpaquePointer?
        XCTAssertEqual(sqlite3_open(path, &lock), SQLITE_OK)
        defer { sqlite3_exec(lock, "ROLLBACK", nil, nil, nil); sqlite3_close(lock) }
        XCTAssertEqual(sqlite3_exec(lock, "BEGIN IMMEDIATE", nil, nil, nil), SQLITE_OK)
        XCTAssertThrowsError(try flow.updateSupplementalDraft("잠금 중 편집", for: goalID))
        XCTAssertThrowsError(try flow.confirmSupplementalContext("잠금 중 확인", for: goalID))
        XCTAssertEqual(flow.supplementalContext, saved)
        XCTAssertEqual(sqlite3_exec(lock, "ROLLBACK", nil, nil, nil), SQLITE_OK)
        try flow.updateSupplementalDraft(boundary, for: goalID)
        XCTAssertEqual(try makeFlow(provider).supplementalContext?.draftText, boundary)
        let calls = await provider.requests
        XCTAssertEqual(calls.count, 1)
    }

    func testOnlyChangedConfirmationInvalidatesPendingResponseAndDeletionCannotReviveInput() async throws {
        for event in ["draft", "same", "changed", "delete"] {
            let held = HeldProvider(.action(first))
            let flow = try makeFlow(held)
            try await startGoal(flow, "진행 중 보충 입력 \(event)")
            let goalID = try XCTUnwrap(flow.goalDetails?.id)
            try flow.updateSupplementalDraft("편집 중", for: goalID)
            switch event {
            case "same": try flow.confirmSupplementalContext("", for: goalID)
            case "changed": try flow.confirmSupplementalContext("확인한 새 내용", for: goalID)
            case "delete": try flow.deleteGoal(goalID, confirmed: true)
            default: break
            }
            await held.release()
            await flow.waitForSuggestion()
            let reopened = try makeFlow(UnavailableSuggestionProvider())
            if ["draft", "same"].contains(event) {
                guard case .currentAction(let card, _) = reopened.screen else { return XCTFail("\(reopened.screen)") }
                XCTAssertEqual(card.task, first.task)
                XCTAssertEqual(reopened.supplementalContext?.draftText, event == "draft" ? "편집 중" : nil)
            } else if event == "changed" {
                XCTAssertEqual(reopened.screen, .awaitingFirstAction(goal: "진행 중 보충 입력 changed", problem: .interrupted))
                XCTAssertEqual(reopened.supplementalContext?.confirmedText, "확인한 새 내용")
            } else {
                XCTAssertEqual(reopened.screen, .goalInput)
                XCTAssertFalse(reopened.goals.contains { $0.id == goalID })
                XCTAssertEqual(try count("SELECT COUNT(*) FROM app_metadata WHERE key = 'supplemental_context:\(goalID)'"), 0)
                XCTAssertThrowsError(try flow.updateSupplementalDraft("늦은 초안", for: goalID))
            }
            let calls = await held.requests
            XCTAssertEqual(calls, 1)
        }
    }

    func testSupplementalInputPreservesOriginalContextProgressAndSameNamedGoalOnDeletion() async throws {
        let provider = ScriptedProvider([.action(first), .action(second), .noAction, .insufficientInfo(try InsufficientInfoFixture.reason())])
        let flow = try makeFlow(provider)
        try flow.updateGoalInput(GoalInput(statement: "같은 목표", currentState: "기존 상태", blocker: "기존 막힘",
                                          materialLinks: "https://example.com/original", materialExcerpt: "직접 고른 자료"))
        try flow.prepareGoal()
        await flow.waitForSuggestion()
        let originalID = try XCTUnwrap(flow.goalDetails?.id)
        try flow.confirmGoal(completionCriteria: "완료 기준")
        await flow.waitForSuggestion()
        guard case .currentAction(let card, _) = flow.screen else { return XCTFail() }
        try flow.recordResult("원래 행동 결과", for: card.id)
        try flow.complete()
        await flow.waitForSuggestion()
        try flow.deferAction()
        await flow.waitForSuggestion()
        let progress = flow.screen
        let details = flow.goalDetails
        try flow.updateSupplementalDraft("첫 목표 초안", for: originalID)
        try flow.confirmSupplementalContext("첫 목표 확인값", for: originalID)
        try flow.updateSupplementalDraft("수정 중", for: originalID)
        XCTAssertEqual(flow.screen, progress)
        XCTAssertEqual(flow.goalDetails, details)
        try await startGoal(flow, "같은 목표")
        await flow.waitForSuggestion()
        let otherID = try XCTUnwrap(flow.goalDetails?.id)
        XCTAssertNotEqual(originalID, otherID)
        XCTAssertEqual(flow.supplementalContext?.confirmedText, "")
        try flow.confirmSupplementalContext("다른 목표 확인값", for: otherID)
        try flow.updateSupplementalDraft("다른 목표 초안", for: otherID)
        let otherContext = flow.supplementalContext
        try flow.startNewGoal()
        let newInput = GoalInput(statement: "새 목표 초안", materialLinks: "https://example.com/original")
        try flow.updateGoalInput(newInput)
        let external = directory.appendingPathComponent("original.txt")
        try Data("외부 원본".utf8).write(to: external)
        try flow.selectGoal(originalID)
        XCTAssertThrowsError(try flow.updateSupplementalDraft("다른 목표의 늦은 입력", for: otherID))
        XCTAssertEqual(flow.supplementalContext?.draftText, "수정 중")
        XCTAssertEqual(flow.goals.first?.completedActionCount, 1)
        let database = try AppDatabase(path: path)
        try await database.writer.write { db in
            try db.execute(sql: "CREATE TRIGGER reject_context_delete BEFORE DELETE ON app_metadata WHEN OLD.key = 'supplemental_context:\(originalID)' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        }
        XCTAssertThrowsError(try flow.deleteGoal(originalID, confirmed: true))
        XCTAssertEqual(try makeFlow(provider).supplementalContext, flow.supplementalContext)
        XCTAssertEqual(flow.screen, progress)
        try await database.writer.write { try $0.execute(sql: "DROP TRIGGER reject_context_delete") }
        try flow.deleteGoal(originalID, confirmed: true)
        XCTAssertEqual(flow.goalInput, newInput)
        try flow.selectGoal(otherID)
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.supplementalContext, otherContext)
        XCTAssertEqual(reopened.goals.map(\.id), [otherID])
        XCTAssertEqual(try String(contentsOf: external, encoding: .utf8), "외부 원본")
        let calls = await provider.requests
        XCTAssertEqual(calls.count, 4)
    }

    func testSharedSourceDecisionsPreserveProgressOnBothAdapters() async throws {
        let shared = try InsufficientInfoFixture.json()
        for server in [false, true] {
            for scenario in shared["checker_cases"] as! [[String: Any]] {
                let id = scenario["id"] as! String
                let source = scenario["input"] as! [String: Any]
                let expected = scenario["expected"] as! String
                let generated = (scenario["generated"] ?? shared["generated"]) as! [String: Any]
                DevelopmentTransport.store.reset()
                DevelopmentTransport.store.handler = { http in
                    let payload = try JSONSerialization.jsonObject(with: http.httpBody!) as! [String: Any]
                    let input = payload["input"] as! [String: Any]
                    var response: [String: Any] = ["disposition": expected]
                    if expected == "accepted" {
                        var proposal = generated
                        proposal.removeValue(forKey: "facts")
                        proposal.removeValue(forKey: "reduction")
                        proposal["remaining_work"] = input["remaining_work"]
                        proposal["preserved_completed_ids"] = input["completed_ids"]
                        response["proposal"] = proposal
                    }
                    return (200, try JSONSerialization.data(withJSONObject: response))
                }
                let config = URLSessionConfiguration.ephemeral
                config.protocolClasses = [DevelopmentTransport.self]
                let session = URLSession(configuration: config)
                let provider = server
                    ? HTTPActionSuggestionProvider.server(baseURL: URL(string: "https://api.example.invalid")!, token: { "test-identity" }, session: session)
                    : HTTPActionSuggestionProvider.development(baseURL: URL(string: "http://127.0.0.1:8080")!, token: nil, session: session)
                let flow = try makeFlow(provider)
                if flow.screen != .goalInput { try flow.startNewGoal() }
                let goal = source["goal"] as! String
                try flow.updateGoalInput(GoalInput(statement: goal,
                    currentState: (source["available"] as! [String]).joined(separator: "\n"),
                    blocker: source["current_blocker"] as! String))
                try flow.prepareGoal()
                await flow.waitForSuggestion()
                try flow.confirmGoal(completionCriteria: goal)
                await flow.waitForSuggestion()
                if expected == "accepted" {
                    if generated["status"] as? String == "need_info" {
                        XCTAssertEqual(flow.screen, .actionQuestion(generated["action"] as! String), id)
                    } else {
                        guard case .insufficientInfo(let notice, false) = flow.screen else { return XCTFail(id) }
                        XCTAssertEqual(notice.reason, generated["reason"] as? String, id)
                    }
                } else {
                    XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: goal, problem: .failure(expected == "uncertain" ? .undecidable : .rejected)), id)
                    XCTAssertNil(flow.supplementalContext?.lastNotice, id)
                }
                let http = try XCTUnwrap(DevelopmentTransport.store.requests.last)
                let payload = try JSONSerialization.jsonObject(with: http.httpBody!) as! [String: Any]
                let input = payload["input"] as! [String: Any]
                XCTAssertEqual(input["request_kind"] as? String, source["request_kind"] as? String, id)
                let available = input["available"] as! [String]
                for fact in source["available"] as! [String] {
                    XCTAssertTrue(available.contains { $0.contains(fact) }, id)
                }
                XCTAssertEqual(try makeFlow(provider).screen, flow.screen, id)
                XCTAssertEqual(DevelopmentTransport.store.requests.count, 1, id)
                XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0, id)
                XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 0, id)
            }
        }
    }

    func testDeleteAllGoalsClearsGoalsRecordsAndDrafts() async throws {
        let provider = ScriptedProvider([.action(first), .action(second)])
        let flow = try makeFlow(provider)
        let card = try await firstCard(flow)
        try flow.updateDraft("작성 중", for: card.id)
        try await startGoal(flow, "두 번째 목표")
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.goals.count, 2)
        let ids = flow.goals.map(\.id)
        try await AppDatabase(path: path).writer.write { db in
            for id in ids {
                for prefix in ["goal_input", "suggestion_input", "supplemental_context"] {
                    try db.execute(sql: "INSERT OR REPLACE INTO app_metadata (key, value) VALUES (?, '남은 입력')", arguments: ["\(prefix):\(id)"])
                }
            }
        }
        let requestsBefore = await provider.requests.count
        XCTAssertThrowsError(try flow.deleteAllGoals())

        try flow.deleteAllGoals(confirmed: true)
        XCTAssertEqual(flow.screen, .goalInput)
        XCTAssertTrue(flow.goals.isEmpty)
        for table in ["goal", "action", "action_note", "suggestion_request"] {
            XCTAssertEqual(try count("SELECT COUNT(*) FROM \(table)"), 0, table)
        }
        XCTAssertEqual(try count("SELECT COUNT(*) FROM app_metadata WHERE key != 'schema_version'"), 0)

        var input = GoalInput()
        input.statement = "제출하지 않은 목표"
        try flow.updateGoalInput(input)
        try flow.deleteAllGoals(confirmed: true)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM app_metadata WHERE key != 'schema_version'"), 0)
        XCTAssertEqual(try makeFlow(SuspendedProvider()).goalInput, GoalInput())
        let requestsAfter = await provider.requests.count
        XCTAssertEqual(requestsAfter, requestsBefore)
    }

    func testDeleteAllGoalsWhileWaitingCancelsAndIgnoresTheLateResult() async throws {
        do {
            let flow = try makeFlow(ScriptedProvider([.action(first)]))
            _ = try await firstCard(flow)
        }
        let provider = SuspendedProvider()
        let flow = try makeFlow(provider)
        try flow.makeSmaller()
        try flow.deleteAllGoals(confirmed: true)
        await flow.waitForSuggestion()
        let cancelled = await provider.cancelled
        XCTAssertTrue(cancelled)
        XCTAssertEqual(flow.screen, .goalInput)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0)
    }

    func testSharedHTTPNoticeAndMetadataStayIsolatedAndDeleteAtomically() async throws {
        let response = try InsufficientInfoFixture.response()
        DevelopmentTransport.store.reset()
        DevelopmentTransport.store.handler = { _ in (200, response) }
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [DevelopmentTransport.self]
        let provider = HTTPActionSuggestionProvider.development(baseURL: URL(string: "http://127.0.0.1:8080")!, token: nil, session: URLSession(configuration: config))
        let flow = try makeFlow(provider)
        try await startGoal(flow, "과거 경력 사실 정리")
        await flow.waitForSuggestion()
        guard case .insufficientInfo(let notice, false) = flow.screen else { return XCTFail("\(flow.screen)") }
        let originalScreen = flow.screen
        let originalID = try XCTUnwrap(flow.goalDetails?.id)
        XCTAssertEqual(notice.reason, try InsufficientInfoFixture.reason())
        XCTAssertEqual(notice.requestKind, .firstAction)
        XCTAssertEqual(notice.goalRevision, 1)
        XCTAssertEqual(notice.inputFingerprint.count, 64)
        XCTAssertLessThan(abs(notice.receivedAt.timeIntervalSinceNow), 10)
        try await startGoal(flow, "과거 경력 사실 정리")
        await flow.waitForSuggestion()
        let otherID = try XCTUnwrap(flow.goalDetails?.id)
        let otherScreen = flow.screen
        try flow.selectGoal(originalID)
        XCTAssertEqual(flow.screen, originalScreen)
        try flow.editGoalStatement("달라진 문구")
        guard case .insufficientInfo(let previous, true) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(previous, notice)
        XCTAssertEqual(try makeFlow(provider).screen, flow.screen)
        try flow.editGoalStatement("과거 경력 사실 정리")
        XCTAssertEqual(flow.screen, originalScreen)
        let database = try AppDatabase(path: path)
        try await database.writer.write { db in
            try db.execute(sql: "CREATE TRIGGER reject_notice_delete BEFORE DELETE ON app_metadata WHEN OLD.key = 'supplemental_context:\(originalID)' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        }
        XCTAssertThrowsError(try flow.deleteGoal(originalID, confirmed: true))
        XCTAssertEqual(flow.goals.count, 2)
        XCTAssertEqual(flow.screen, originalScreen)
        XCTAssertEqual(try makeFlow(provider).screen, originalScreen)
        try await database.writer.write { try $0.execute(sql: "DROP TRIGGER reject_notice_delete") }
        try flow.deleteGoal(originalID, confirmed: true)
        XCTAssertEqual(flow.screen, .goalInput)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM app_metadata WHERE key = 'supplemental_context:\(originalID)'"), 0)
        try flow.selectGoal(otherID)
        XCTAssertEqual(flow.screen, otherScreen)
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, otherScreen)
        XCTAssertEqual(reopened.goals.map(\.id), [otherID])
        XCTAssertEqual(DevelopmentTransport.store.requests.count, 2)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 0)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request WHERE kind = 'first_action' AND status = 'applied'"), 1)
    }

    func testLateInsufficientInfoCannotReplaceCancelledSwitchedChangedOrInterruptedState() async throws {
        for event in ["cancel", "switch", "revision", "reopen", "stop", "delete"] {
            let held = HeldProvider(.insufficientInfo(try InsufficientInfoFixture.reason()))
            let flow = try makeFlow(held)
            try await startGoal(flow, "늦은 안내 \(event)")
            switch event {
            case "cancel": try flow.cancelSuggestion()
            case "switch": try flow.startNewGoal()
            case "revision":
                try await AppDatabase(path: path).writer.write { try $0.execute(sql: "UPDATE goal SET revision = revision + 1") }
            case "reopen": _ = try makeFlow(UnavailableSuggestionProvider())
            case "stop": try flow.stopGoal()
            default: try flow.deleteGoal(XCTUnwrap(flow.goalDetails?.id), confirmed: true)
            }
            await held.release()
            await flow.waitForSuggestion()
            if case .insufficientInfo = flow.screen { XCTFail("late notice applied after \(event)") }
            if case .insufficientInfo = try makeFlow(UnavailableSuggestionProvider()).screen { XCTFail("late notice restored after \(event)") }
            let calls = await held.requests
            XCTAssertEqual(calls, 1)
        }
        XCTAssertEqual(try count("SELECT COUNT(*) FROM app_metadata WHERE key LIKE 'supplemental_context:%'"), 0)
    }

    func testUnsavedInsufficientInfoRemainsFailureUntilSuccessfullySaved() async throws {
        let provider = LockingProvider(path: path, candidate: .insufficientInfo(try InsufficientInfoFixture.reason()))
        let flow = try makeFlow(provider)
        try await startGoal(flow, "과거 경력 사실 정리")
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "과거 경력 사실 정리", problem: .failure(.failed)))
        await provider.releaseLock()
        XCTAssertEqual(try count("SELECT COUNT(*) FROM app_metadata WHERE key LIKE 'supplemental_context:%'"), 0)
        try flow.retrySuggestion()
        await flow.waitForSuggestion()
        guard case .insufficientInfo = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(try makeFlow(UnavailableSuggestionProvider()).screen, flow.screen)
    }

    func testFirstActionFailureKeepsGoalWithoutAutomaticRetry() async throws {
        let failures = SuggestionFailure.allCases
        let provider = ScriptedProvider(failures.map { .failure($0) })
        let flow = try makeFlow(provider)
        for failure in failures {
            let goal = "목표 \(failure.rawValue)"
            try await startGoal(flow, goal)
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
            try await startGoal(flow, "목표 \(failure.rawValue)")
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
        try await startGoal(flow, "통계 강의 1장 끝내기")
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "통계 강의 1장 끝내기", problem: nil))

        try flow.retrySuggestion()
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request WHERE kind != 'goal_preparation'"), 1)

        await provider.release()
        await flow.waitForSuggestion()
        guard case .currentAction(let card, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, first.task)
        let requests = await provider.requests
        XCTAssertEqual(requests, 1)
    }

    func testCompletionWhileAnotherSuggestionIsPendingSucceeds() async throws {
        let provider = ScriptedProvider([.action(first), .action(second)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
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
        guard case .currentAction(let card, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, second.task)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 1)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request WHERE kind = 'smaller' AND status = 'interrupted'"), 1)
    }

    func testCancelReachesProviderAndKeepsGoal() async throws {
        let provider = SuspendedProvider()
        let flow = try makeFlow(provider)
        try await startGoal(flow, "통계 강의 1장 끝내기")
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
        try await startGoal(flow, "방 한 칸 정리하기")
        try flow.cancelSuggestion()
        await provider.release()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "방 한 칸 정리하기", problem: .cancelled))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action"), 0)
    }

    func testResultForChangedRevisionIsNotApplied() async throws {
        let provider = HeldProvider(.action(first))
        let flow = try makeFlow(provider)
        try await startGoal(flow, "방 한 칸 정리하기")
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
            try await startGoal(flow, "통계 강의 1장 끝내기")
            XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "통계 강의 1장 끝내기", problem: nil))
        }

        let provider = ScriptedProvider([.action(first)])
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, .awaitingFirstAction(goal: "통계 강의 1장 끝내기", problem: .interrupted))
        let untouched = await provider.requests
        XCTAssertTrue(untouched.isEmpty)

        try reopened.retrySuggestion()
        await reopened.waitForSuggestion()
        guard case .currentAction(let card, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(card.task, first.task)
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction])
    }

    func testPendingNextActionIsInterruptedAfterReopenAndKeepsCompletion() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first)]))
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
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
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "주간 업무 보고서 초안 쓰기", problem: .failure(.failed)))

        await provider.releaseLock()
        try flow.retrySuggestion()
        await flow.waitForSuggestion()
        guard case .currentAction(let card, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, first.task)
    }

    // MARK: - 더 작게와 되돌리기 (#55)

    private let smaller = ProposedAction(task: "메모 제목만 확인하기", doneWhen: "메모 제목을 읽었다", estimatedMinutes: 1)

    private func card(_ action: ProposedAction) -> ProposedAction {
        ProposedAction(task: action.task, doneWhen: action.doneWhen, estimatedMinutes: action.estimatedMinutes)
    }

    private func status(ofTask task: String) throws -> String? {
        try AppDatabase(path: path).writer.read { db in
            try String.fetchOne(db, sql: "SELECT status FROM action WHERE task = ?", arguments: [task])
        }
    }

    func testSmallerThenCompleteKeepsSplitSourceAndGoalOpen() async throws {
        let provider = ScriptedProvider([.action(first), .minimalAction(smaller), .action(second)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        guard case .currentAction(let source, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try await AppDatabase(path: path).writer.write { db in
            try db.execute(sql: "UPDATE goal SET blocker = '시간이 부족함', completion_criteria = '초안 한 쪽'")
        }

        try flow.makeSmaller()
        // 질문 없이 바로 요청한다.
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: .waiting))
        await flow.waitForSuggestion()
        guard case .currentAction(let small, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(small.task, smaller.task)
        XCTAssertEqual(small.origin, ActionCard.Origin(id: source.id, task: first.task))
        XCTAssertEqual(try status(ofTask: first.task), "split")

        try flow.complete()
        await flow.waitForSuggestion()
        XCTAssertEqual(try status(ofTask: smaller.task), "done")
        XCTAssertEqual(try status(ofTask: first.task), "split")
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 1)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM goal WHERE status = 'active' AND completion_criteria = '초안 한 쪽'"), 1)

        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction, .smaller, .nextAction])
        XCTAssertEqual(requests[1].currentAction, card(first))
        XCTAssertEqual(requests[1].blocker, "시간이 부족함")
        // 작은 행동을 완료한 뒤에도 분할 원본의 남은 범위를 다음 요청에 전달한다.
        XCTAssertEqual(requests[2].currentAction, card(first))
        XCTAssertEqual(requests[2].completedTasks, [smaller.task])
    }

    func testSmallerThenUndoRestoresSourceAndKeepsResults() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(smaller)]))
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        guard case .currentAction(let source, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(let small, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try await AppDatabase(path: path).writer.write { db in
            try db.execute(
                sql: "INSERT INTO action_note (action_id, body, is_draft, updated_at) VALUES (?, '제목: 주간 보고', 0, CURRENT_TIMESTAMP)",
                arguments: [small.id]
            )
        }

        try flow.undoSplit()
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: nil))
        XCTAssertEqual(try status(ofTask: smaller.task), "deferred")
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action_note"), 1)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 0)

        // 분할 원본은 되돌릴 대상이 없다.
        try flow.undoSplit()
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: nil))

        let reopened = try makeFlow(ScriptedProvider([SuggestionCandidate]()))
        XCTAssertEqual(reopened.screen, .currentAction(source, smaller: nil))
    }

    func testRepeatedSmallerSendsSplitSourcesAndUndoesOneStep() async throws {
        let smallest = ProposedAction(task: "메모 앱 열기", doneWhen: "메모 앱이 열려 있다", estimatedMinutes: 1)
        let provider = ScriptedProvider([.action(first), .action(smaller), .action(smallest)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(let small, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(let tiny, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(tiny.origin, ActionCard.Origin(id: small.id, task: smaller.task))

        // 공급자가 같은 행동을 이미 나눴는지 알 수 있게 분할 원본을 처음 것부터 담는다.
        let requests = await provider.requests
        XCTAssertEqual(requests[1].splitSources, [])
        XCTAssertEqual(requests[2].currentAction, card(smaller))
        XCTAssertEqual(requests[2].splitSources, [first.task])

        try flow.undoSplit()
        XCTAssertEqual(flow.screen, .currentAction(small, smaller: nil))
    }

    func testQuestionAnswerIsSavedAsBlockerAndSentWithNextRequest() async throws {
        let question = "가장 먼저 막히는 지점은 무엇인가요?"
        let provider = ScriptedProvider([.action(first), .question(question), .action(smaller)])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        guard case .currentAction(let source, nil) = flow.screen else { return XCTFail("\(flow.screen)") }

        try flow.makeSmaller()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: .question(question)))
        XCTAssertEqual(try status(ofTask: first.task), "current")
        let requestID = try XCTUnwrap(flow.suggestionInput?.requestID)
        try flow.updateSuggestionInput(" 어떤 자료를 봐야 할지 모름 ", for: requestID)

        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, .currentAction(source, smaller: .question(question)))
        XCTAssertEqual(reopened.suggestionInput?.text, " 어떤 자료를 봐야 할지 모름 ")
        XCTAssertThrowsError(try reopened.answerQuestion("  "))
        try reopened.answerQuestion(" 어떤 자료를 봐야 할지 모름 ")
        XCTAssertEqual(reopened.screen, .currentAction(source, smaller: .waiting))
        XCTAssertNil(reopened.suggestionInput)
        await reopened.waitForSuggestion()
        guard case .currentAction(let small, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(small.task, smaller.task)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM goal WHERE blocker = '어떤 자료를 봐야 할지 모름'"), 1)

        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction, .smaller, .smaller])
        XCTAssertNil(requests[1].blocker)
        XCTAssertEqual(requests[2].blocker, "어떤 자료를 봐야 할지 모름")
    }

    func testUndoWhileWaitingEndsRequestAndSmallerCanStartAgain() async throws {
        do {
            let flow = try makeFlow(ScriptedProvider([.action(first), .action(smaller)]))
            try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
            await flow.waitForSuggestion()
            try flow.makeSmaller()
            await flow.waitForSuggestion()
        }
        let provider = HeldProvider(.action(smaller))
        let flow = try makeFlow(provider)
        guard case .currentAction(let small, nil) = flow.screen, let origin = small.origin else { return XCTFail("\(flow.screen)") }
        try flow.makeSmaller()
        try flow.undoSplit()
        guard case .currentAction(let source, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(source.id, origin.id)
        await provider.release()
        await flow.waitForSuggestion()
        // 되돌린 뒤 도착한 결과는 적용하지 않는다.
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: nil))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'interrupted'"), 1)

        try flow.makeSmaller()
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: .waiting))
        await provider.release()
        await flow.waitForSuggestion()
        guard case .currentAction(let again, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(again.origin?.id, source.id)
    }

    func testAnsweredQuestionIsNotAskedAgain() async throws {
        let question = "가장 먼저 막히는 지점은 무엇인가요?"
        let flow = try makeFlow(ScriptedProvider([.action(first), .question(question), .question(" \(question)")]))
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        guard case .currentAction(let source, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        try flow.answerQuestion("자료 위치를 모름")
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: .problem(.unsuitable)))
    }

    func testUnansweredQuestionCanBeAskedAgain() async throws {
        let answered = "가장 먼저 막히는 지점은 무엇인가요?"
        let skipped = "어떤 자료가 먼저 필요한가요?"
        let flow = try makeFlow(ScriptedProvider([
            .action(first), .question(answered), .action(smaller), .action(second),
            .question(skipped), .action(third), .question(skipped),
        ]))
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        try flow.answerQuestion("자료 위치를 모름")
        await flow.waitForSuggestion()
        try flow.complete()
        await flow.waitForSuggestion()
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(_, .question(skipped)) = flow.screen else { return XCTFail("\(flow.screen)") }
        // 질문에 답하지 않고 완료한다. 같은 질문을 다시 받으면 보여준다.
        try flow.complete()
        await flow.waitForSuggestion()
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(let card, .question(skipped)) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, third.task)
    }

    func testUndoWhileWaitingCancelsProvider() async throws {
        do {
            let flow = try makeFlow(ScriptedProvider([.action(first), .action(smaller)]))
            try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
            await flow.waitForSuggestion()
            try flow.makeSmaller()
            await flow.waitForSuggestion()
        }
        let provider = SuspendedProvider()
        let flow = try makeFlow(provider)
        try flow.makeSmaller()
        try flow.undoSplit()
        await flow.waitForSuggestion()
        let cancelled = await provider.cancelled
        XCTAssertTrue(cancelled)
    }

    func testUnsavedSmallerResultCanBeRetried() async throws {
        do {
            let flow = try makeFlow(ScriptedProvider([.action(first)]))
            try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
            await flow.waitForSuggestion()
        }
        let provider = LockingProvider(path: path, candidate: .action(smaller))
        let flow = try makeFlow(provider)
        guard case .currentAction(let source, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: .problem(.failure(.failed))))

        await provider.releaseLock()
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(let small, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(small.task, smaller.task)
    }

    func testDraftSaveAfterUnsavedSuggestionResultKeepsRetryAvailable() async throws {
        do {
            let flow = try makeFlow(ScriptedProvider([.action(first)]))
            _ = try await firstCard(flow)
        }
        let provider = LockingProvider(path: path, candidate: .action(smaller))
        let flow = try makeFlow(provider)
        guard case .currentAction(let source, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        await provider.releaseLock()
        try flow.updateDraft("실패 뒤에도 입력한 초안", for: source.id)
        guard case .currentAction(let current, let status) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(current.draft, "실패 뒤에도 입력한 초안")
        XCTAssertEqual(status, .problem(.failure(.failed)))
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(let small, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(small.task, smaller.task)
    }

    func testSmallerFailureAndCancelKeepCurrentAction() async throws {
        let provider = ScriptedProvider([.success(.action(first)), .failure(.timedOut), .success(.question(" "))])
        let flow = try makeFlow(provider)
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        guard case .currentAction(let source, nil) = flow.screen else { return XCTFail("\(flow.screen)") }

        try flow.makeSmaller()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: .problem(.failure(.timedOut))))
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .currentAction(source, smaller: .problem(.unsuitable)))

        let waiting = try makeFlow(SuspendedProvider())
        try waiting.makeSmaller()
        try waiting.makeSmaller()
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'pending'"), 1)
        try waiting.cancelSuggestion()
        XCTAssertEqual(waiting.screen, .currentAction(source, smaller: .problem(.cancelled)))
        XCTAssertEqual(try status(ofTask: first.task), "current")
    }

    // MARK: - 나중에·보류 중·재개 (#56)

    private func firstCard(_ flow: ProgressFlow) async throws -> ActionCard {
        try await startGoal(flow, "주간 업무 보고서 초안 쓰기")
        await flow.waitForSuggestion()
        guard case .currentAction(let card, nil) = flow.screen else { XCTFail("\(flow.screen)"); throw CancellationError() }
        return card
    }

    func testDeferRequestsReplacementAndKeepsDeferredAction() async throws {
        let provider = ScriptedProvider([.action(first), .action(second)])
        let flow = try makeFlow(provider)
        let deferred = try await firstCard(flow)
        try await AppDatabase(path: path).writer.write { db in
            try db.execute(
                sql: "INSERT INTO action_note (action_id, body, is_draft, updated_at) VALUES (?, '메모 위치 확인', 0, CURRENT_TIMESTAMP)",
                arguments: [deferred.id]
            )
        }

        try flow.deferAction()
        XCTAssertEqual(flow.screen, .onHold(deferred: [deferred], status: .waiting))
        await flow.waitForSuggestion()
        guard case .currentAction(let replacement, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(replacement.task, second.task)
        XCTAssertNil(replacement.origin)
        XCTAssertEqual(try status(ofTask: first.task), "deferred")
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 0)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM action_note"), 1)

        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction, .replacement])
        XCTAssertEqual(requests[1].deferredTasks, [first.task])
    }

    func testDeferWithoutReplacementShowsOnHoldWithoutSwitchingGoal() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(third), .action(first), .noAction, .action(first)]))
        try await startGoal(flow, "다른 목표")
        await flow.waitForSuggestion()
        let deferred = try await firstCard(flow)

        try flow.deferAction()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .onHold(deferred: [deferred], status: .noAction))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM app_metadata WHERE key = 'selected_goal_id' AND value = (SELECT MAX(id) FROM goal)"), 1)

        // 같은 행동을 대체 후보로 받으면 적용하지 않는다.
        try flow.retrySuggestion()
        XCTAssertEqual(flow.screen, .onHold(deferred: [deferred], status: .waiting))
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .onHold(deferred: [deferred], status: .problem(.unsuitable)))
    }

    func testResumeRestoresDeferredActionWithoutResolvingAnything() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first), .noAction]))
        let deferred = try await firstCard(flow)
        try await AppDatabase(path: path).writer.write { db in
            try db.execute(sql: "UPDATE goal SET blocker = '자료가 없음'")
        }
        try flow.deferAction()
        await flow.waitForSuggestion()

        try flow.resume(deferred.id)
        XCTAssertEqual(flow.screen, .currentAction(deferred, smaller: nil))
        XCTAssertEqual(try status(ofTask: first.task), "current")
        XCTAssertEqual(try count("SELECT COUNT(*) FROM goal WHERE blocker = '자료가 없음'"), 1)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 0)
    }

    func testResumeFromCurrentActionDefersTheCurrentOne() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
        let deferred = try await firstCard(flow)
        try flow.deferAction()
        await flow.waitForSuggestion()
        guard case .currentAction(let replacement, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(flow.goalDetails?.deferredActions.map(\.id), [deferred.id])

        try flow.resume(deferred.id)
        guard case .currentAction(let resumed, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(resumed.id, deferred.id)
        XCTAssertEqual(try status(ofTask: second.task), "deferred")
        XCTAssertEqual(flow.goalDetails?.deferredActions.map(\.id), [replacement.id])
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 0)
        XCTAssertThrowsError(try flow.resume(deferred.id))
        // 재개할 행동이 없으면 현재 행동을 보류한 쓰기도 되돌린다.
        XCTAssertThrowsError(try flow.resume(Int64.max))
        XCTAssertEqual(try status(ofTask: first.task), "current")
        let reopened = try makeFlow(SuspendedProvider())
        guard case .currentAction(let restored, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(restored.id, deferred.id)
        XCTAssertEqual(reopened.goalDetails?.deferredActions.map(\.id), [replacement.id])
    }

    func testResumeWhileSmallerWaitsEndsTheRequest() async throws {
        let deferredID: Int64
        do {
            let flow = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
            deferredID = try await firstCard(flow).id
            try flow.deferAction()
            await flow.waitForSuggestion()
        }
        let provider = SuspendedProvider()
        let flow = try makeFlow(provider)
        try flow.makeSmaller()
        try flow.resume(deferredID)
        await flow.waitForSuggestion()
        let cancelled = await provider.cancelled
        XCTAssertTrue(cancelled)
        guard case .currentAction(let resumed, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(resumed.id, deferredID)
        XCTAssertEqual(try count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'pending'"), 0)
    }

    func testOnHoldSurvivesReopenAndPendingReplacementCanBeRetried() async throws {
        let deferred: ActionCard
        do {
            let flow = try makeFlow(ScriptedProvider([.action(first), .noAction]))
            deferred = try await firstCard(flow)
            try flow.deferAction()
            await flow.waitForSuggestion()
        }
        XCTAssertEqual(try makeFlow(SuspendedProvider()).screen, .onHold(deferred: [deferred], status: .noAction))

        do {
            let flow = try makeFlow(SuspendedProvider())
            try flow.resume(deferred.id)
            try flow.deferAction()
            XCTAssertEqual(flow.screen, .onHold(deferred: [deferred], status: .waiting))
        }
        let provider = ScriptedProvider([.action(second)])
        let reopened = try makeFlow(provider)
        XCTAssertEqual(reopened.screen, .onHold(deferred: [deferred], status: .problem(.interrupted)))
        try reopened.retrySuggestion()
        await reopened.waitForSuggestion()
        guard case .currentAction(let card, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(card.task, second.task)
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.replacement])
    }

    func testDeferredActionCanBeResumedAfterNextActionFails() async throws {
        let flow = try makeFlow(ScriptedProvider([.success(.action(first)), .success(.action(second)), .failure(.timedOut)]))
        let deferred = try await firstCard(flow)
        try flow.deferAction()
        await flow.waitForSuggestion()
        try flow.complete()
        // 다음 행동을 기다리는 동안에도 보류한 행동을 보여준다.
        XCTAssertEqual(flow.screen, .onHold(deferred: [deferred], status: .waiting))
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .onHold(deferred: [deferred], status: .problem(.failure(.timedOut))))
        XCTAssertEqual(try makeFlow(SuspendedProvider()).screen, .onHold(deferred: [deferred], status: .problem(.failure(.timedOut))))

        try flow.resume(deferred.id)
        XCTAssertEqual(flow.screen, .currentAction(deferred, smaller: nil))
        XCTAssertEqual(try count("SELECT COUNT(*) FROM completion"), 1)
    }

    func testFailedNextActionIsRetriedAsNextActionWhileOnHold() async throws {
        let provider = ScriptedProvider([.success(.action(first)), .success(.action(second)), .failure(.timedOut), .success(.action(third))])
        let flow = try makeFlow(provider)
        _ = try await firstCard(flow)
        try flow.deferAction()
        await flow.waitForSuggestion()
        try flow.complete()
        await flow.waitForSuggestion()
        try flow.retrySuggestion()
        await flow.waitForSuggestion()
        guard case .currentAction(let card, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(card.task, third.task)
        // 실패한 다음 행동은 같은 종류로 다시 요청한다. 보류 목록은 계속 담는다.
        let requests = await provider.requests
        XCTAssertEqual(requests.map(\.kind), [.firstAction, .replacement, .nextAction, .nextAction])
        XCTAssertEqual(requests[3].deferredTasks, [first.task])
    }

    func testNextActionMatchingDeferredActionIsNotApplied() async throws {
        let provider = ScriptedProvider([.action(first), .action(second), .action(first)])
        let flow = try makeFlow(provider)
        let deferred = try await firstCard(flow)
        try flow.deferAction()
        await flow.waitForSuggestion()
        try flow.complete()
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .onHold(deferred: [deferred], status: .problem(.unsuitable)))
        let requests = await provider.requests
        XCTAssertEqual(requests[2].kind, .nextAction)
        XCTAssertEqual(requests[2].deferredTasks, [first.task])
    }

    func testResumedUndoneSmallActionHasNoUndo() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(smaller), .noAction]))
        _ = try await firstCard(flow)
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(let small, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.undoSplit()
        try flow.deferAction()
        await flow.waitForSuggestion()
        guard case .onHold(let deferred, .noAction) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(deferred.map(\.task), [first.task, smaller.task])

        // 분할 원본이 이미 보류라서 작은 행동을 재개해도 되돌릴 원본이 없다.
        try flow.resume(small.id)
        guard case .currentAction(let resumed, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertNil(resumed.origin)
    }

    func testDraftAutosavesAndSurvivesReopenWithoutBecomingResult() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first)]))
        let card = try await firstCard(flow)
        try flow.updateDraft("첫 문장\n작성 중", for: card.id)
        try flow.updateDraft("고친 문장\n작성 중", for: card.id)

        let reopened = try makeFlow(UnavailableSuggestionProvider())
        guard case .currentAction(let restored, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(restored.draft, "고친 문장\n작성 중")
        XCTAssertTrue(restored.results.isEmpty)
        XCTAssertEqual(restored.id, card.id)
    }

    func testRecordedResultAndNewDraftSurviveDeferAndResume() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first), .noAction]))
        let card = try await firstCard(flow)
        try flow.updateDraft("남긴 문장", for: card.id)
        try flow.recordResult("남긴 문장", for: card.id)
        guard case .currentAction(let saved, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(saved.results.map(\.body), ["남긴 문장"])
        XCTAssertEqual(saved.draft, "")
        try flow.updateDraft("다음 문장 작성 중", for: card.id)
        try flow.deferAction()
        await flow.waitForSuggestion()

        let reopened = try makeFlow(UnavailableSuggestionProvider())
        try reopened.resume(card.id)
        guard case .currentAction(let restored, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(restored.results.map(\.body), ["남긴 문장"])
        XCTAssertEqual(restored.draft, "다음 문장 작성 중")
    }

    func testCardRestoresTargetLinksAndEarlierResultsForSameTarget() async throws {
        var initial = first
        initial.targetName = "업무 보고서"
        var other = second
        other.targetName = "다른 문서"
        var next = third
        next.targetName = "업무 보고서"
        next.targetDescription = "이번 주 업무를 적은 문서"
        next.materialLinks = [URL(string: "https://example.com/report")!]
        let flow = try makeFlow(ScriptedProvider([.action(initial), .action(other), .action(next)]))
        let first = try await firstCard(flow)
        try flow.recordResult("확인한 기간: 10월 첫째 주", for: first.id)
        try flow.updateDraft("이 초안은 앞선 결과가 아니다", for: first.id)
        try flow.complete()
        await flow.waitForSuggestion()
        guard case .currentAction(let second, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        try flow.recordResult("다른 문서의 결과", for: second.id)
        try flow.complete()
        await flow.waitForSuggestion()

        let reopened = try makeFlow(UnavailableSuggestionProvider())
        guard case .currentAction(let restored, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(restored.targetName, "업무 보고서")
        XCTAssertEqual(restored.targetDescription, "이번 주 업무를 적은 문서")
        XCTAssertEqual(restored.materialLinks, [URL(string: "https://example.com/report")!])
        XCTAssertEqual(restored.previousResults.map(\.body), ["확인한 기간: 10월 첫째 주"])
        XCTAssertTrue(restored.results.isEmpty)
        XCTAssertEqual(restored.draft, "")
    }

    func testSplitInheritsTargetAndNotesSurviveUndoAndResume() async throws {
        var initial = first
        initial.targetName = "업무 보고서"
        initial.targetDescription = "내가 작성 중인 보고서"
        initial.materialLinks = [URL(string: "https://example.com/report")!]
        let flow = try makeFlow(ScriptedProvider([.action(initial), .action(smaller), .noAction]))
        let source = try await firstCard(flow)
        try flow.recordResult("원본에 남긴 결과", for: source.id)
        try flow.updateDraft("원본 초안", for: source.id)
        try flow.makeSmaller()
        await flow.waitForSuggestion()
        guard case .currentAction(let small, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(small.targetName, initial.targetName)
        XCTAssertEqual(small.targetDescription, initial.targetDescription)
        XCTAssertEqual(small.materialLinks, initial.materialLinks)
        XCTAssertEqual(small.previousResults.map(\.body), ["원본에 남긴 결과"])
        try flow.recordResult("작은 행동의 결과", for: small.id)
        try flow.updateDraft("작은 행동 초안", for: small.id)
        try flow.undoSplit()
        let reopened = try makeFlow(UnavailableSuggestionProvider())
        guard case .currentAction(let restored, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(restored.draft, "원본 초안")
        XCTAssertEqual(restored.results.map(\.body), ["원본에 남긴 결과"])
        XCTAssertEqual(restored.previousResults.map(\.body), ["작은 행동의 결과"])
        try reopened.deferAction()
        await reopened.waitForSuggestion()
        try reopened.resume(small.id)
        guard case .currentAction(let resumed, nil) = reopened.screen else { return XCTFail("\(reopened.screen)") }
        XCTAssertEqual(resumed.results.map(\.body), ["작은 행동의 결과"])
        XCTAssertEqual(resumed.draft, "작은 행동 초안")
    }

    func testNonWebMaterialLinkIsRejected() async throws {
        var proposed = first
        proposed.materialLinks = [URL(string: "file:///private/tmp/report")!]
        let flow = try makeFlow(ScriptedProvider([.action(proposed)]))
        try await startGoal(flow, "보고서 정리")
        await flow.waitForSuggestion()
        XCTAssertEqual(flow.screen, .awaitingFirstAction(goal: "보고서 정리", problem: .unsuitable))
    }

    func testFailedResultCommitKeepsDraftAndScreenAndCanRetry() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first)]))
        let card = try await firstCard(flow)
        try flow.updateDraft("지우면 안 되는 초안", for: card.id)
        let before = flow.screen
        let database = try AppDatabase(path: path)
        try await database.writer.write { db in
            try db.execute(sql: "CREATE TRIGGER reject_draft_delete BEFORE DELETE ON action_note BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        }
        XCTAssertThrowsError(try flow.recordResult("지우면 안 되는 초안", for: card.id))
        XCTAssertEqual(flow.screen, before)
        XCTAssertEqual(try makeFlow(UnavailableSuggestionProvider()).screen, before)
        try await database.writer.write { db in try db.execute(sql: "DROP TRIGGER reject_draft_delete") }
        try flow.recordResult("지우면 안 되는 초안", for: card.id)
        guard case .currentAction(let saved, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(saved.results.map(\.body), ["지우면 안 되는 초안"])
        XCTAssertEqual(saved.draft, "")
    }

    func testRunSavesGoalInputDraftBeforeCommand() throws {
        let flow = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        var drafts = Drafts()
        drafts.goalInput.statement = "자료 정리"
        try flow.run(saving: drafts) { try flow.prepareGoal() }
        XCTAssertEqual(flow.goalDetails?.statement, "자료 정리")
    }

    func testRunDoesNotRunCommandWhenDraftSaveFails() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first)]))
        let card = try await firstCard(flow)
        let before = flow.screen
        let database = try AppDatabase(path: path)
        try await database.writer.write { db in
            try db.execute(sql: "CREATE TRIGGER reject_draft BEFORE INSERT ON action_note BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        }
        XCTAssertThrowsError(try flow.run(saving: Drafts(actionNote: "다시 볼 메모")) { try flow.deferAction() })
        XCTAssertEqual(flow.screen, before)
        try await database.writer.write { db in try db.execute(sql: "DROP TRIGGER reject_draft") }
        try flow.run(saving: Drafts(actionNote: "다시 볼 메모")) { try flow.deferAction() }
        try flow.resume(card.id)
        guard case .currentAction(let resumed, _) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertEqual(resumed.draft, "다시 볼 메모")
    }

    func testStaleActionCannotSaveDraftIntoAnotherCard() async throws {
        let flow = try makeFlow(ScriptedProvider([.action(first), .action(second)]))
        let old = try await firstCard(flow)
        try flow.complete()
        await flow.waitForSuggestion()
        let current = flow.screen
        XCTAssertThrowsError(try flow.updateDraft("늦은 입력", for: old.id))
        XCTAssertThrowsError(try flow.recordResult("늦은 결과", for: old.id))
        XCTAssertEqual(flow.screen, current)
        XCTAssertEqual(try makeFlow(UnavailableSuggestionProvider()).screen, current)
    }

    func testSameTargetNameInDifferentGoalDoesNotShareResults() async throws {
        var proposed = first
        proposed.targetName = "같은 이름의 자료"
        let flow = try makeFlow(ScriptedProvider([.action(proposed), .action(proposed)]))
        let card = try await firstCard(flow)
        try flow.recordResult("이 목표에만 남긴 결과", for: card.id)
        try await startGoal(flow, "다른 목표")
        await flow.waitForSuggestion()
        guard case .currentAction(let current, nil) = flow.screen else { return XCTFail("\(flow.screen)") }
        XCTAssertTrue(current.previousResults.isEmpty)
        XCTAssertTrue(current.results.isEmpty)
        XCTAssertEqual(current.draft, "")
    }

    func testProductMigrationKeepsBootstrapMetadata() throws {
        _ = try makeFlow(UnavailableSuggestionProvider(), preparing: false)
        let value = try AppDatabase(path: path).writer.read { db in
            try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = 'schema_version'")
        }
        XCTAssertEqual(value, "1")
    }
}

/// 목표 준비 요청에 목표 문장을 완료 조건으로 답한다. 다른 요청은 감싼 공급자에 넘긴다.
private struct GoalPreparing: ActionSuggestionProvider {
    let wrapped: any ActionSuggestionProvider
    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        request.kind == .goalPreparation ? .goalSummary(request.goal) : try await wrapped.suggest(request)
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
        // 공급자가 호출되지 않았는데 테스트가 통과하지 않게 한다.
        precondition(gate != nil, "suggest가 호출되지 않았다")
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

final class CandidatePolicyTests: XCTestCase {
    private let action = ProposedAction(task: "관련 메모 하나 열기", doneWhen: "메모가 화면에 열려 있다", estimatedMinutes: 3)

    private func request(_ kind: SuggestionKind) -> SuggestionRequest {
        SuggestionRequest(kind: kind, goal: "자료 정리", currentAction: action, completedTasks: [], deferredTasks: ["보류한 일"])
    }

    func testCandidateTypeMustMatchRequestKind() {
        let all: [SuggestionKind] = [.goalPreparation, .firstAction, .nextAction, .smaller, .replacement]
        let cases: [(SuggestionCandidate, Set<SuggestionKind>)] = [
            (.goalSummary("메모가 정리돼 있다"), [.goalPreparation]),
            (.noAction, [.replacement]),
            (.question("어느 메모인가요?"), Set(all)),
            (.insufficientInfo("지금은 근거가 부족해요"), [.firstAction, .nextAction, .smaller, .replacement]),
            (.action(ProposedAction(task: "새 일", doneWhen: "끝남", estimatedMinutes: 1)), [.firstAction, .nextAction, .smaller, .replacement]),
            (.minimalAction(ProposedAction(task: "새 일", doneWhen: "끝남", estimatedMinutes: 1)), [.firstAction, .nextAction, .smaller, .replacement]),
        ]
        for (candidate, accepted) in cases {
            for kind in all {
                XCTAssertEqual(CandidatePolicy.accept(candidate, for: request(kind)) != nil, accepted.contains(kind), "\(candidate) \(kind)")
            }
        }
    }

    func testIncompleteOrClaimingActionsAreRejectedAndTextIsTrimmed() {
        var blank = action; blank.task = " \n"
        var noCondition = action; noCondition.doneWhen = ""
        var noMinutes = action; noMinutes.estimatedMinutes = 0
        var goalDone = action; goalDone.marksGoalComplete = true
        var currentDone = action; currentDone.marksCurrentActionComplete = true
        var badLink = action; badLink.materialLinks = [URL(string: "file:///tmp/a")!]
        for invalid in [blank, noCondition, noMinutes, goalDone, currentDone, badLink] {
            XCTAssertNil(CandidatePolicy.accept(.action(invalid), for: request(.firstAction)), "\(invalid)")
        }
        XCTAssertNil(CandidatePolicy.accept(.goalSummary("  "), for: request(.goalPreparation)))
        XCTAssertNil(CandidatePolicy.accept(.question("\n"), for: request(.smaller)))
        var padded = action; padded.task = "  새 일\n"; padded.targetName = " "
        XCTAssertEqual(CandidatePolicy.accept(.action(padded), for: request(.firstAction)),
                       .action(ProposedAction(task: "새 일", doneWhen: action.doneWhen, estimatedMinutes: 3)))
        XCTAssertEqual(CandidatePolicy.accept(.question(" 어느 메모인가요? "), for: request(.smaller)), .question("어느 메모인가요?"))
    }

    func testSmallerExcludesCurrentActionAndOthersExcludeDeferredActions() {
        var deferred = action; deferred.task = " 보류한 일"
        XCTAssertNil(CandidatePolicy.accept(.action(action), for: request(.smaller)))
        XCTAssertNotNil(CandidatePolicy.accept(.action(deferred), for: request(.smaller)))
        for kind: SuggestionKind in [.firstAction, .nextAction, .replacement] {
            XCTAssertNil(CandidatePolicy.accept(.minimalAction(deferred), for: request(kind)), "\(kind)")
            XCTAssertNotNil(CandidatePolicy.accept(.action(action), for: request(kind)), "\(kind)")
        }
    }
}

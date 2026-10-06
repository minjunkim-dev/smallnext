import Foundation
import GRDB
import Observation
import OSLog

struct ActionCard: Equatable, Identifiable, Sendable {
    let id: Int64
    let task: String
    let doneWhen: String
    let estimatedMinutes: Int
    /// 이 행동을 나눈 분할 원본이다. 분할로 만든 행동만 값이 있다.
    var origin: Origin? = nil

    struct Origin: Equatable, Sendable {
        let id: Int64
        let task: String
    }
}

enum SuggestionProblem: Equatable, Sendable {
    case failure(SuggestionFailure)
    /// 구조 검사를 통과하지 못한 후보다.
    case unsuitable
    /// 앱 종료 등으로 끝나지 않았거나 이전 상태에 대한 요청이다.
    case interrupted
    /// 사용자가 취소한 요청이다.
    case cancelled
}

/// 현재 행동의 ‘더 작게’ 요청 상태다.
enum SmallerStatus: Equatable, Sendable {
    case waiting
    /// 공급자가 행동 대신 확인 질문 하나를 돌려줬다. 답은 막힘 원인으로 저장한다.
    case question(String)
    case problem(SuggestionProblem)
}

/// 대기 화면의 `problem`이 nil이면 제안을 기다리는 중이다. 값이 있으면 '다시 시도'를 기다린다.
enum ProgressScreen: Equatable, Sendable {
    case goalInput
    /// 첫 행동을 받기 전이다. 입력한 목표를 유지한다.
    case awaitingFirstAction(goal: String, problem: SuggestionProblem?)
    case currentAction(ActionCard, smaller: SmallerStatus?)
    /// 완료 후 다음 행동을 받기 전이다. 완료 기록을 유지한다.
    case awaitingNextAction(problem: SuggestionProblem?)
}

enum ProgressFlowError: Error {
    case emptyGoal
    case goalNotFound
    case emptyAnswer
    case splitSourceNotFound
}

/// 화면이 호출하는 진행 흐름의 유일한 진입점이다.
/// 모든 명령은 GRDB 트랜잭션 하나로 저장한다. 저장에 실패하면 `screen`을 바꾸지 않는다.
@MainActor
@Observable
final class ProgressFlow {
    private(set) var screen: ProgressScreen = .goalInput

    @ObservationIgnored private let database: AppDatabase
    @ObservationIgnored private let provider: any ActionSuggestionProvider
    @ObservationIgnored private var suggestionTask: Task<Void, Never>?
    @ObservationIgnored private let logger = Logger(subsystem: "dev.smallnext.app", category: "progress")

    init(database: AppDatabase, provider: any ActionSuggestionProvider) throws {
        self.database = database
        self.provider = provider
        screen = try database.writer.write { db in
            try db.execute(sql: "UPDATE suggestion_request SET status = 'interrupted' WHERE status = 'pending'")
            return try Self.loadScreen(db)
        }
    }

    func createGoal(_ text: String) throws {
        let statement = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !statement.isEmpty else { throw ProgressFlowError.emptyGoal }
        try perform { db in
            let now = Date()
            try db.execute(
                sql: "INSERT INTO goal (statement, created_at, updated_at) VALUES (?, ?, ?)",
                arguments: [statement, now, now]
            )
            let goalID = db.lastInsertedRowID
            try db.execute(
                sql: """
                INSERT INTO app_metadata (key, value) VALUES ('selected_goal_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                arguments: [String(goalID)]
            )
            return try Self.insertRequest(db, goalID: goalID, kind: .firstAction)
        }
    }

    /// 현재 행동만 완료한다. 이미 완료한 행동에 대한 호출은 무시한다.
    func complete() throws {
        guard case .currentAction(let card, _) = screen else { return }
        try perform { db in
            try db.execute(sql: "UPDATE action SET status = 'done' WHERE id = ? AND status = 'current'", arguments: [card.id])
            guard db.changesCount == 1,
                  let goalID = try Int64.fetchOne(db, sql: "SELECT goal_id FROM action WHERE id = ?", arguments: [card.id])
            else { return nil }
            try db.execute(
                sql: "INSERT INTO completion (action_id, completed_at) VALUES (?, ?)",
                arguments: [card.id, Date()]
            )
            try Self.bumpRevision(db, goalID: goalID)
            // 다른 종류의 대기 요청은 이전 상태에 대한 요청이다. 완료를 막지 않도록 끝낸다.
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            return try Self.insertRequest(db, goalID: goalID, kind: .nextAction)
        }
    }

    /// 현재 행동보다 쉬운 행동 하나를 바로 요청한다. 질문을 먼저 하지 않는다. 기다리는 중이면 무시한다.
    func makeSmaller() throws {
        guard case .currentAction(_, let smaller) = screen, smaller != .waiting else { return }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            return try Self.insertRequest(db, goalID: goalID, kind: .smaller)
        }
    }

    /// 확인 질문의 답을 막힘 원인으로 저장하고, 그 원인을 담아 더 쉬운 행동을 다시 요청한다.
    func answerQuestion(_ text: String) throws {
        guard case .currentAction(_, .question) = screen else { return }
        let answer = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty else { throw ProgressFlowError.emptyAnswer }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            try db.execute(sql: "UPDATE goal SET blocker = ? WHERE id = ?", arguments: [answer, goalID])
            try Self.bumpRevision(db, goalID: goalID)
            return try Self.insertRequest(db, goalID: goalID, kind: .smaller)
        }
    }

    /// 분할 직전 행동을 현재 행동으로 되돌린다. 작은 행동은 보류로 남긴다. 행동 결과는 지우지 않는다.
    func undoSplit() throws {
        guard case .currentAction(let card, _) = screen, let origin = card.origin else { return }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            try db.execute(sql: "UPDATE action SET status = 'deferred' WHERE id = ? AND status = 'current'", arguments: [card.id])
            guard db.changesCount == 1 else { return nil }
            try db.execute(sql: "UPDATE action SET status = 'current' WHERE id = ? AND status = 'split'", arguments: [origin.id])
            guard db.changesCount == 1 else { throw ProgressFlowError.splitSourceNotFound }
            try Self.bumpRevision(db, goalID: goalID)
            // 작은 행동에 대한 대기 요청은 이전 상태에 대한 요청이다.
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            return nil
        }
    }

    /// 실패·중단·취소한 제안만 다시 요청한다. 기다리는 중이면 무시한다.
    func retrySuggestion() throws {
        guard screen.suggestionProblem != nil else { return }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            // 결과 저장에 실패해 pending으로 남은 요청을 끝낸다. 늦게 온 결과는 적용하지 않는다.
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            return try Self.insertRequest(db, goalID: goalID, kind: Self.hasCompletion(db, goalID: goalID) ? .nextAction : .firstAction)
        }
    }

    /// 기다리는 제안을 취소한다. 저장한 뒤 공급자 작업을 취소한다. 늦게 온 결과는 적용하지 않는다.
    func cancelSuggestion() throws {
        guard screen.isWaitingForSuggestion else { return }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            try Self.endPendingRequests(db, goalID: goalID, status: "cancelled")
            return nil
        }
        suggestionTask?.cancel()
    }

    /// 진행 중인 제안 요청이 끝날 때까지 기다린다. 테스트에서 쓴다.
    func waitForSuggestion() async {
        await suggestionTask?.value
    }

    // MARK: - 제안 요청

    private struct PendingSuggestion: Sendable {
        let id: Int64
        let goalID: Int64
        let revision: Int
        let request: SuggestionRequest
    }

    private func perform(_ command: @Sendable (Database) throws -> PendingSuggestion?) throws {
        let (pending, screen) = try database.writer.write { db in
            (try command(db), try Self.loadScreen(db))
        }
        self.screen = screen
        if let pending { start(pending) }
    }

    private func start(_ pending: PendingSuggestion) {
        let provider = provider
        suggestionTask?.cancel()
        suggestionTask = Task {
            let outcome: Result<SuggestionCandidate, SuggestionFailure>
            do {
                outcome = .success(try await provider.suggest(pending.request))
            } catch {
                outcome = .failure(error as? SuggestionFailure ?? .failed)
            }
            finish(pending, outcome)
        }
    }

    private func finish(_ pending: PendingSuggestion, _ outcome: Result<SuggestionCandidate, SuggestionFailure>) {
        do {
            screen = try database.writer.write { db in
                try Self.apply(db, pending, outcome)
                return try Self.loadScreen(db)
            }
        } catch {
            logger.error("Suggestion result was not saved: \(String(describing: type(of: error)), privacy: .public)")
            // 취소한 요청의 결과는 화면에 반영하지 않는다.
            guard !Task.isCancelled else { return }
            switch screen {
            case .awaitingFirstAction(let goal, nil):
                screen = .awaitingFirstAction(goal: goal, problem: .failure(.failed))
            case .awaitingNextAction(nil):
                screen = .awaitingNextAction(problem: .failure(.failed))
            case .currentAction(let card, .waiting):
                screen = .currentAction(card, smaller: .problem(.failure(.failed)))
            default:
                break
            }
        }
    }

    /// 요청이 아직 `pending`이고 목표 리비전이 같을 때만 결과를 적용한다.
    /// 리비전이 바뀐 요청은 `interrupted`로 끝낸다.
    private nonisolated static func apply(
        _ db: Database,
        _ pending: PendingSuggestion,
        _ outcome: Result<SuggestionCandidate, SuggestionFailure>
    ) throws {
        guard let row = try Row.fetchOne(
            db,
            sql: "SELECT r.status, g.revision FROM suggestion_request r JOIN goal g ON g.id = r.goal_id WHERE r.id = ?",
            arguments: [pending.id]
        ), row["status"] == "pending" else { return }
        guard row["revision"] == pending.revision else {
            return try finishRequest(db, pending.id, status: "interrupted", reason: nil)
        }

        let isSmaller = pending.request.kind == .smaller
        let proposed: ProposedAction
        switch outcome {
        case .failure(let failure):
            return try finishRequest(db, pending.id, status: "failed", reason: failure.rawValue)
        case .success(.question(let text)):
            // 확인 질문은 더 작게 요청에서만 받는다.
            let question = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard isSmaller, !question.isEmpty else {
                return try finishRequest(db, pending.id, status: "failed", reason: unsuitableReason)
            }
            return try db.execute(
                sql: "UPDATE suggestion_request SET status = 'applied', question = ? WHERE id = ?",
                arguments: [question, pending.id]
            )
        case .success(.action(let candidate)), .success(.minimalAction(let candidate)):
            proposed = candidate
        }
        guard let action = try validated(db, proposed, goalID: pending.goalID),
              action.task != pending.request.currentAction?.task || !isSmaller
        else {
            return try finishRequest(db, pending.id, status: "failed", reason: unsuitableReason)
        }
        // 분할 원본은 내용을 바꾸지 않고 `split`으로 남긴다. 남은 범위와 목표의 완료 조건을 유지한다.
        var sourceID: Int64?
        if isSmaller {
            sourceID = try Int64.fetchOne(
                db, sql: "SELECT id FROM action WHERE goal_id = ? AND status = 'current'", arguments: [pending.goalID]
            )
            guard sourceID != nil else { return try finishRequest(db, pending.id, status: "interrupted", reason: nil) }
            try db.execute(sql: "UPDATE action SET status = 'split' WHERE id = ?", arguments: [sourceID])
        }
        try db.execute(
            sql: """
            INSERT INTO action (goal_id, task, done_when, estimated_minutes, status, split_from_id, sequence)
            VALUES (?, ?, ?, ?, 'current', ?, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM action WHERE goal_id = ?))
            """,
            arguments: [pending.goalID, action.task, action.doneWhen, action.estimatedMinutes, sourceID, pending.goalID]
        )
        try bumpRevision(db, goalID: pending.goalID)
        try finishRequest(db, pending.id, status: "applied", reason: nil)
    }

    /// 앞뒤 공백을 지운 후보를 돌려준다.
    /// 필수 필드가 비었거나, 완료한 행동을 다시 제안했거나, 목표·원래 행동의 완료를 표시한 후보는 nil이다.
    /// 후보 타입은 행동 하나만 담는다.
    private nonisolated static func validated(_ db: Database, _ proposed: ProposedAction, goalID: Int64) throws -> ProposedAction? {
        var action = proposed
        action.task = proposed.task.trimmingCharacters(in: .whitespacesAndNewlines)
        action.doneWhen = proposed.doneWhen.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !action.task.isEmpty, !action.doneWhen.isEmpty, action.estimatedMinutes > 0,
              !action.marksGoalComplete, !action.marksCurrentActionComplete else {
            return nil
        }
        let repeated = try Bool.fetchOne(
            db,
            sql: "SELECT EXISTS (SELECT 1 FROM action WHERE goal_id = ? AND status = 'done' AND task = ?)",
            arguments: [goalID, action.task]
        ) ?? false
        return repeated ? nil : action
    }

    private nonisolated static let unsuitableReason = "unsuitable"

    private nonisolated static func finishRequest(_ db: Database, _ id: Int64, status: String, reason: String?) throws {
        try db.execute(
            sql: "UPDATE suggestion_request SET status = ?, failure_reason = ? WHERE id = ?",
            arguments: [status, reason, id]
        )
    }

    private nonisolated static func endPendingRequests(_ db: Database, goalID: Int64, status: String) throws {
        try db.execute(
            sql: "UPDATE suggestion_request SET status = ? WHERE goal_id = ? AND status = 'pending'",
            arguments: [status, goalID]
        )
    }

    private nonisolated static func bumpRevision(_ db: Database, goalID: Int64) throws {
        try db.execute(
            sql: "UPDATE goal SET revision = revision + 1, updated_at = ? WHERE id = ?",
            arguments: [Date(), goalID]
        )
    }

    private nonisolated static func insertRequest(_ db: Database, goalID: Int64, kind: SuggestionKind) throws -> PendingSuggestion {
        guard let goal = try Row.fetchOne(db, sql: "SELECT statement, revision, blocker FROM goal WHERE id = ?", arguments: [goalID]) else {
            throw ProgressFlowError.goalNotFound
        }
        let revision: Int = goal["revision"]
        try db.execute(
            sql: "INSERT INTO suggestion_request (goal_id, kind, goal_revision, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            arguments: [goalID, kind.rawValue, revision, Date()]
        )
        let requestID = db.lastInsertedRowID
        let completed = try String.fetchAll(
            db,
            sql: """
            SELECT a.task FROM completion c JOIN action a ON a.id = c.action_id
            WHERE a.goal_id = ? ORDER BY c.id
            """,
            arguments: [goalID]
        )
        return PendingSuggestion(
            id: requestID,
            goalID: goalID,
            revision: revision,
            request: SuggestionRequest(
                kind: kind,
                goal: goal["statement"],
                currentAction: try contextAction(db, goalID: goalID, kind: kind),
                completedTasks: completed,
                blocker: goal["blocker"]
            )
        )
    }

    /// 더 작게는 현재 행동을, 다음 행동은 방금 완료한 작은 행동의 분할 원본을 담는다.
    private nonisolated static func contextAction(_ db: Database, goalID: Int64, kind: SuggestionKind) throws -> ProposedAction? {
        let sql: String
        switch kind {
        case .smaller:
            sql = "SELECT task, done_when, estimated_minutes FROM action WHERE goal_id = ? AND status = 'current'"
        case .nextAction:
            sql = """
            SELECT p.task, p.done_when, p.estimated_minutes FROM completion c
            JOIN action a ON a.id = c.action_id
            LEFT JOIN action p ON p.id = a.split_from_id AND p.status = 'split'
            WHERE a.goal_id = ? ORDER BY c.id DESC LIMIT 1
            """
        case .firstAction, .replacement:
            return nil
        }
        guard let row = try Row.fetchOne(db, sql: sql, arguments: [goalID]), let task: String = row["task"] else { return nil }
        return ProposedAction(task: task, doneWhen: row["done_when"], estimatedMinutes: row["estimated_minutes"])
    }

    // MARK: - 화면 상태

    private nonisolated static func selectedGoalID(_ db: Database) throws -> Int64? {
        try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = 'selected_goal_id'").flatMap { Int64($0) }
    }

    private nonisolated static func hasCompletion(_ db: Database, goalID: Int64) throws -> Bool {
        try Bool.fetchOne(
            db,
            sql: "SELECT EXISTS (SELECT 1 FROM action WHERE goal_id = ? AND status = 'done')",
            arguments: [goalID]
        ) ?? false
    }

    /// 끝나지 않았거나 적용한 요청이면 nil이다.
    private nonisolated static func requestProblem(_ request: Row) -> SuggestionProblem? {
        let reason: String? = request["failure_reason"]
        switch request["status"] as String {
        case "pending", "applied":
            return nil
        case "failed":
            return reason.flatMap(SuggestionFailure.init(rawValue:)).map { .failure($0) } ?? .unsuitable
        case "cancelled":
            return .cancelled
        default:
            return .interrupted
        }
    }

    private nonisolated static func loadScreen(_ db: Database) throws -> ProgressScreen {
        guard let goalID = try selectedGoalID(db) else { return .goalInput }
        let latest = try Row.fetchOne(
            db,
            sql: """
            SELECT kind, goal_revision, status, failure_reason, question FROM suggestion_request
            WHERE goal_id = ? ORDER BY id DESC LIMIT 1
            """,
            arguments: [goalID]
        )
        if let row = try Row.fetchOne(
            db,
            sql: """
            SELECT a.id, a.task, a.done_when, a.estimated_minutes, a.split_from_id, p.task AS source_task, g.revision
            FROM action a JOIN goal g ON g.id = a.goal_id LEFT JOIN action p ON p.id = a.split_from_id
            WHERE a.goal_id = ? AND a.status = 'current'
            """,
            arguments: [goalID]
        ) {
            let card = ActionCard(
                id: row["id"],
                task: row["task"],
                doneWhen: row["done_when"],
                estimatedMinutes: row["estimated_minutes"],
                origin: (row["split_from_id"] as Int64?).map { ActionCard.Origin(id: $0, task: row["source_task"]) }
            )
            // 같은 리비전의 더 작게 요청만 현재 행동에 대한 요청이다.
            var smaller: SmallerStatus?
            if let latest, latest["kind"] as String == SuggestionKind.smaller.rawValue, latest["goal_revision"] as Int == row["revision"] as Int {
                if let problem = requestProblem(latest) {
                    smaller = .problem(problem)
                } else if let question: String = latest["question"] {
                    smaller = .question(question)
                } else if latest["status"] as String == "pending" {
                    smaller = .waiting
                }
            }
            return .currentAction(card, smaller: smaller)
        }
        let problem = latest.map(requestProblem) ?? .interrupted
        if try hasCompletion(db, goalID: goalID) { return .awaitingNextAction(problem: problem) }
        let goal = try String.fetchOne(db, sql: "SELECT statement FROM goal WHERE id = ?", arguments: [goalID]) ?? ""
        return .awaitingFirstAction(goal: goal, problem: problem)
    }
}

extension ProgressScreen {
    /// 제안을 기다리는 중인지 나타낸다.
    var isWaitingForSuggestion: Bool {
        switch self {
        case .awaitingFirstAction(_, nil), .awaitingNextAction(nil), .currentAction(_, .waiting): true
        default: false
        }
    }

    /// 실패·중단·취소한 제안의 문제다. '다시 시도'를 보여줄 때만 값이 있다.
    var suggestionProblem: SuggestionProblem? {
        switch self {
        case .awaitingFirstAction(_, let problem), .awaitingNextAction(let problem): problem
        case .goalInput, .currentAction: nil
        }
    }
}

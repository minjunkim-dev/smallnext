import Foundation
import GRDB
import Observation
import OSLog

public struct GoalInput: Codable, Equatable, Sendable {
    public var statement = ""
    public var deadline = ""
    public var currentState = ""
    public var blocker = ""
    public var materialLinks = ""
    public var materialExcerpt = ""
    public var availableMinutes = ""

    public init(statement: String = "", deadline: String = "", currentState: String = "", blocker: String = "",
                materialLinks: String = "", materialExcerpt: String = "", availableMinutes: String = "") {
        self.statement = statement
        self.deadline = deadline
        self.currentState = currentState
        self.blocker = blocker
        self.materialLinks = materialLinks
        self.materialExcerpt = materialExcerpt
        self.availableMinutes = availableMinutes
    }
}

/// 화면에 남은 입력 초안이다. 명령 전에 현재 화면에 해당하는 값만 저장한다.
public struct Drafts: Equatable, Sendable {
    var goalInput = GoalInput()
    var answer = ""
    var completionCriteria = ""
    var actionNote = ""
    var supplementalText: String?

    public init(goalInput: GoalInput = GoalInput(), answer: String = "", completionCriteria: String = "", actionNote: String = "", supplementalText: String? = nil) {
        self.goalInput = goalInput
        self.answer = answer
        self.completionCriteria = completionCriteria
        self.actionNote = actionNote
        self.supplementalText = supplementalText
    }
}

public struct SuggestionInput: Equatable, Sendable {
    public let requestID: Int64
    public var text: String?
}

public struct InformationNotice: Equatable, Sendable, Codable {
    public let requestID: Int64
    public let requestKind: SuggestionKind
    public let goalRevision: Int
    public let inputFingerprint: String
    public let reason: String
    public let receivedAt: Date
    let currentActionID: Int64?

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", requestKind = "request_kind", goalRevision = "goal_revision"
        case inputFingerprint = "input_fingerprint", reason, receivedAt = "received_at"
        case currentActionID = "current_action_id"
    }
}

/// 확인 저장값과 미제출 초안은 별개다. 전송은 명시적 재요청에서 연결한다.
public struct SupplementalContext: Codable, Equatable, Sendable {
    public fileprivate(set) var confirmedText = ""
    public fileprivate(set) var draftText: String?
    public fileprivate(set) var lastNotice: InformationNotice?
    fileprivate var confirmedRevision: Int?

    public var hasChangesSinceNotice: Bool {
        guard let lastNotice, let confirmedRevision else { return false }
        return confirmedRevision > lastNotice.goalRevision
    }

    enum CodingKeys: String, CodingKey {
        case confirmedText = "confirmed_text", draftText = "draft_text", lastNotice = "last_notice"
        case confirmedRevision = "confirmed_revision"
    }
}

public struct GoalSummary: Equatable, Identifiable, Sendable {
    public let id: Int64
    public let statement: String
    public let isStopped: Bool
    public let completedActionCount: Int
}

public struct GoalDetails: Equatable, Sendable {
    public let id: Int64
    public let statement: String
    public let completionCriteria: String?
    public var context = GoalContext()
    /// 보류한 행동이다. 현재 행동이 있어도 목표 보기에서 재개할 수 있다.
    public var deferredActions: [ActionCard] = []
}

public struct ActionCard: Equatable, Identifiable, Sendable {
    public let id: Int64
    public let task: String
    public let doneWhen: String
    public let estimatedMinutes: Int
    /// 이 행동을 나눈 분할 원본이다. 분할로 만든 행동만 값이 있다.
    public var origin: Origin? = nil
    public var draft = ""
    public var results: [ActionResult] = []
    public var targetName: String? = nil
    public var targetDescription: String? = nil
    public var materialLinks: [URL] = []
    public var previousResults: [ActionResult] = []

    public struct Origin: Equatable, Sendable {
        public let id: Int64
        public let task: String
    }
}

public struct ActionResult: Equatable, Identifiable, Sendable {
    public let id: Int64
    public let body: String
}

public enum SuggestionProblem: Equatable, Sendable {
    case failure(SuggestionFailure)
    /// 구조 검사를 통과하지 못한 후보다.
    case unsuitable
    /// 앱 종료 등으로 끝나지 않았거나 이전 상태에 대한 요청이다.
    case interrupted
    /// 사용자가 취소한 요청이다.
    case cancelled
}

/// 현재 행동의 ‘더 작게’ 요청 상태다.
public enum SmallerStatus: Equatable, Sendable {
    case waiting
    /// 공급자가 행동 대신 확인 질문 하나를 돌려줬다. 답은 막힘 원인으로 저장한다.
    case question(String)
    case problem(SuggestionProblem)
}

/// 보류 중 화면의 대체 행동 요청 상태다.
public enum HoldStatus: Equatable, Sendable {
    case waiting
    case problem(SuggestionProblem)
    /// 공급자가 선행 조건이 준비된 다른 행동이 없다고 답했다.
    case noAction
}

/// 대기 화면의 `problem`이 nil이면 제안을 기다리는 중이다. 값이 있으면 '다시 시도'를 기다린다.
/// 현재 행동의 `smaller`가 nil이면 더 작게 요청이 없다. 기다리는 중은 `.waiting`이다.
public enum ProgressScreen: Equatable, Sendable {
    case goalInput
    case preparingGoal(question: String?, completionCriteria: String?, problem: SuggestionProblem?)
    /// 첫 행동을 받기 전이다. 입력한 목표를 유지한다.
    case awaitingFirstAction(goal: String, problem: SuggestionProblem?)
    case currentAction(ActionCard, smaller: SmallerStatus?)
    case insufficientInfo(InformationNotice, isPrevious: Bool)
    /// 확정 목표의 행동 요청에서 받은 실제 미답 질문이다. 더 작게는 기존 현재 행동에 표시한다.
    case actionQuestion(String)
    /// 완료 후 다음 행동을 받기 전이다. 완료 기록을 유지한다.
    case awaitingNextAction(problem: SuggestionProblem?)
    /// 현재 행동이 없고 보류한 행동이 있다. 보류한 행동을 생성 순서대로 담아 재개할 수 있게 한다.
    case onHold(deferred: [ActionCard], status: HoldStatus)
    /// 수행을 중단한 목표다. 마지막 현재 행동의 입력과 결과는 보관한다.
    case stoppedGoal(ActionCard?)
}

public enum ProgressFlowError: Error {
    case emptyGoal
    case goalNotFound
    case emptyAnswer
    case answerExceedsRequestLimit
    case splitSourceNotFound
    case deferredActionNotFound
    case actionNotCurrent
    case emptyResult
    case goalInputNotActive
    case invalidGoalContext
    case goalNotReady
    case deletionNotConfirmed
    case supplementalContextTooLarge
    case supplementalRequestTooLarge
}

/// 화면이 호출하는 진행 흐름의 유일한 진입점이다.
/// 모든 명령은 GRDB 트랜잭션 하나로 저장한다. 저장에 실패하면 `screen`을 바꾸지 않는다.
@MainActor
@Observable
public final class ProgressFlow {
    public private(set) var screen: ProgressScreen = .goalInput
    public private(set) var goalInput = GoalInput()
    public private(set) var goalDetails: GoalDetails?
    public private(set) var goals: [GoalSummary] = []
    public private(set) var suggestionInput: SuggestionInput?
    /// nil은 이 목표에 저장 레코드가 없다는 뜻이다. 빈 초안과 구분한다.
    public private(set) var supplementalContext: SupplementalContext?
    public var canRequestWithNewInformation: Bool {
        guard case .insufficientInfo(let notice, _) = screen, let goalID = goalDetails?.id,
              supplementalContext?.confirmedText.isEmpty == false else { return false }
        return (try? database.writer.read { try Self.canRepropose($0, goalID: goalID, noticeID: notice.requestID) }) == true
    }
    var timingEnabled = SuggestionTiming.enabled
    public private(set) var timingSample: SuggestionTiming?
    @ObservationIgnored private var commandStart: TimeInterval?

    /// 사용자 명령 하나를 실행한다. 입력 초안을 먼저 저장하고, 시간 측정은 명령 시작부터 잰다.
    /// 초안 저장에 실패하면 명령을 실행하지 않는다.
    public func run(saving drafts: Drafts? = nil, _ command: () throws -> Void) throws {
        commandStart = timingEnabled ? SuggestionTiming.now : nil
        defer { commandStart = nil }
        if let drafts { try save(drafts) }
        try command()
    }

    private func save(_ drafts: Drafts) throws {
        if let text = drafts.supplementalText, let goalID = goalDetails?.id,
           supplementalContext?.draftText != text {
            try updateSupplementalDraft(text, for: goalID)
        }
        if let input = suggestionInput {
            let text: String
            let saved: String
            if case .preparingGoal(_, let criteria?, _) = screen {
                text = drafts.completionCriteria
                saved = input.text ?? criteria
            } else {
                text = drafts.answer
                saved = input.text ?? ""
            }
            if text != saved { try updateSuggestionInput(text, for: input.requestID) }
        }
        if screen == .goalInput, drafts.goalInput != goalInput {
            try updateGoalInput(drafts.goalInput)
        }
        // 자동 저장에 실패한 입력이 있으면 화면을 떠나기 전에 다시 저장한다.
        if case .currentAction(let card, _) = screen, card.draft != drafts.actionNote {
            try updateDraft(drafts.actionNote, for: card.id)
        }
    }

    @ObservationIgnored private let database: AppDatabase
    @ObservationIgnored private let provider: any ActionSuggestionProvider
    @ObservationIgnored private var suggestionTask: Task<Void, Never>?
    /// 결과 저장 실패로 DB에 pending이 남은 요청이다. 다음 성공한 명령에서 실패 상태도 저장한다.
    @ObservationIgnored private var unsavedSuggestionID: Int64?
    @ObservationIgnored private var dismissedNoticeID: Int64?
    @ObservationIgnored private let logger = Logger(subsystem: "dev.smallnext.app", category: "progress")

    public init(database: AppDatabase, provider: any ActionSuggestionProvider) throws {
        self.database = database
        self.provider = provider
        screen = try database.writer.write { db in
            try db.execute(sql: "UPDATE suggestion_request SET status = 'interrupted' WHERE status = 'pending'")
            return try Self.loadScreen(db)
        }
        goalInput = try database.writer.read(Self.loadGoalInput)
        goalDetails = try database.writer.read(Self.loadGoalDetails)
        goals = try database.writer.read(Self.loadGoals)
        let initialScreen = screen
        suggestionInput = try database.writer.read { try Self.loadSuggestionInput($0, screen: initialScreen) }
        supplementalContext = try database.writer.read(Self.loadSelectedSupplementalContext)
    }

    public func updateSupplementalDraft(_ text: String, for goalID: Int64) throws {
        guard text.utf8.count <= 32 * 1024 else { throw ProgressFlowError.supplementalContextTooLarge }
        try perform { db in
            guard try Self.selectedGoalID(db) == goalID else { throw ProgressFlowError.goalNotFound }
            var context = try Self.loadSupplementalContext(db, goalID: goalID) ?? SupplementalContext()
            context.draftText = text
            try Self.saveSupplementalContext(db, context, goalID: goalID)
            return nil
        }
    }

    public func confirmSupplementalContext(_ text: String, for goalID: Int64) throws {
        guard text.utf8.count <= 32 * 1024 else { throw ProgressFlowError.supplementalContextTooLarge }
        try perform { db in
            guard try Self.selectedGoalID(db) == goalID else { throw ProgressFlowError.goalNotFound }
            var context = try Self.loadSupplementalContext(db, goalID: goalID) ?? SupplementalContext()
            if context.confirmedText != text {
                try Self.bumpRevision(db, goalID: goalID)
                try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
                context.confirmedText = text
                context.confirmedRevision = try Int.fetchOne(db, sql: "SELECT revision FROM goal WHERE id = ?", arguments: [goalID])
            }
            context.draftText = nil
            try Self.saveSupplementalContext(db, context, goalID: goalID)
            return nil
        }
    }

    /// 확인 질문의 답과 수정 중인 완료 조건도 초안으로 보존한다. 이전 요청의 늦은 입력은 거부한다.
    public func updateSuggestionInput(_ text: String, for requestID: Int64) throws {
        try perform { db in
            guard let input = try Self.loadSuggestionInput(db, screen: Self.loadScreen(db)), input.requestID == requestID,
                  let goalID = try Self.selectedGoalID(db) else { throw ProgressFlowError.goalNotReady }
            try db.execute(sql: "INSERT INTO app_metadata (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                           arguments: ["suggestion_input:\(goalID)", text])
            return nil
        }
    }

    private nonisolated static func loadSuggestionInput(_ db: Database, screen: ProgressScreen) throws -> SuggestionInput? {
        switch screen {
        case .preparingGoal(.some, _, nil), .preparingGoal(_, .some, nil), .currentAction(_, .question), .actionQuestion: break
        default: return nil
        }
        guard let goalID = try selectedGoalID(db),
              let requestID = try Int64.fetchOne(db, sql: "SELECT MAX(id) FROM suggestion_request WHERE goal_id = ?", arguments: [goalID]) else { return nil }
        return SuggestionInput(requestID: requestID,
                               text: try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = ?", arguments: ["suggestion_input:\(goalID)"]))
    }

    /// 같은 목표를 다시 선택해도 그 목표의 제안은 중단하지 않는다.
    public func selectGoal(_ goalID: Int64) throws {
        if goalDetails?.id == goalID { return }
        try perform { db in
            guard try Bool.fetchOne(db, sql: "SELECT EXISTS (SELECT 1 FROM goal WHERE id = ?)", arguments: [goalID]) == true else {
                throw ProgressFlowError.goalNotFound
            }
            if let previous = try Self.selectedGoalID(db) {
                try Self.endPendingRequests(db, goalID: previous, status: "interrupted")
            }
            try db.execute(sql: "INSERT INTO app_metadata (key, value) VALUES ('selected_goal_id', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                           arguments: [String(goalID)])
            return nil
        }
        dismissedNoticeID = nil
        suggestionTask?.cancel()
    }

    private nonisolated static func loadGoals(_ db: Database) throws -> [GoalSummary] {
        try Row.fetchAll(db, sql: """
            SELECT g.id, g.statement, g.status,
                   (SELECT COUNT(*) FROM completion c JOIN action a ON a.id = c.action_id WHERE a.goal_id = g.id) AS completed_count
            FROM goal g ORDER BY g.id
            """).map {
                GoalSummary(id: $0["id"], statement: $0["statement"], isStopped: $0["status"] as String == "stopped",
                            completedActionCount: $0["completed_count"])
            }
    }

    /// 새 목표 입력으로 이동한다. 작성 중인 새 목표 입력은 따로 보존한다.
    public func startNewGoal() throws {
        try perform { db in
            if let previous = try Self.selectedGoalID(db) {
                try Self.endPendingRequests(db, goalID: previous, status: "interrupted")
            }
            try db.execute(sql: "DELETE FROM app_metadata WHERE key = 'selected_goal_id'")
            return nil
        }
        dismissedNoticeID = nil
        suggestionTask?.cancel()
    }

    /// 문구만 수정한다. 완료 조건과 행동·입력·완료 기록은 유지한다.
    public func editGoalStatement(_ text: String) throws {
        guard let statement = Self.nonempty(text) else { throw ProgressFlowError.emptyGoal }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { throw ProgressFlowError.goalNotFound }
            try db.execute(sql: "UPDATE goal SET statement = ?, updated_at = ? WHERE id = ?", arguments: [statement, Date(), goalID])
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            // 확인 중인 목표도 재실행 후 수정한 문구로 복구한다.
            if let text = try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = ?", arguments: ["goal_input:\(goalID)"]) {
                var input = try JSONDecoder().decode(GoalInput.self, from: Data(text.utf8))
                input.statement = statement
                try db.execute(sql: "UPDATE app_metadata SET value = ? WHERE key = ?",
                               arguments: [String(decoding: try JSONEncoder().encode(input), as: UTF8.self), "goal_input:\(goalID)"])
            }
            try db.execute(sql: "UPDATE suggestion_request SET status = 'interrupted' WHERE goal_id = ? AND status = 'applied' AND question IS NOT NULL AND answer IS NULL",
                           arguments: [goalID])
            return nil
        }
        suggestionTask?.cancel()
    }

    /// 목표 수행을 중단한다. 행동과 입력·결과·완료 기록은 보관한다.
    public func stopGoal() throws {
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { throw ProgressFlowError.goalNotFound }
            try db.execute(sql: "UPDATE goal SET status = 'stopped', updated_at = ? WHERE id = ?", arguments: [Date(), goalID])
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            return nil
        }
        suggestionTask?.cancel()
    }

    /// 확인한 목표 하나만 삭제한다. 소속 행동·입력·완료·제안 요청은 외래 키로 함께 지운다.
    public func deleteGoal(_ goalID: Int64, confirmed: Bool = false) throws {
        guard confirmed else { throw ProgressFlowError.deletionNotConfirmed }
        let deletingSelected = goalDetails?.id == goalID
        try perform { db in
            try db.execute(sql: "DELETE FROM goal WHERE id = ?", arguments: [goalID])
            guard db.changesCount == 1 else { throw ProgressFlowError.goalNotFound }
            try db.execute(sql: "DELETE FROM app_metadata WHERE key = ?", arguments: ["goal_input:\(goalID)"])
            try db.execute(sql: "DELETE FROM app_metadata WHERE key = ?", arguments: ["suggestion_input:\(goalID)"])
            try db.execute(sql: "DELETE FROM app_metadata WHERE key = ?", arguments: ["supplemental_context:\(goalID)"])
            if try Self.selectedGoalID(db) == goalID {
                try db.execute(sql: "DELETE FROM app_metadata WHERE key = 'selected_goal_id'")
            }
            return nil
        }
        if deletingSelected { suggestionTask?.cancel() }
    }

    /// 제출하기 전의 입력도 그대로 저장한다. 입력 초안은 확인한 목표가 아니다.
    public func updateGoalInput(_ input: GoalInput) throws {
        guard screen == .goalInput else { throw ProgressFlowError.goalInputNotActive }
        try database.writer.write { db in
            try db.execute(
                sql: "INSERT INTO app_metadata (key, value) VALUES ('goal_input', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                arguments: [String(decoding: try JSONEncoder().encode(input), as: UTF8.self)]
            )
        }
        goalInput = input
    }

    private nonisolated static func loadGoalInput(_ db: Database) throws -> GoalInput {
        let key: String
        if let goalID = try selectedGoalID(db),
           try Bool.fetchOne(db, sql: "SELECT NOT is_confirmed FROM goal WHERE id = ?", arguments: [goalID]) == true {
            key = "goal_input:\(goalID)"
        } else { key = "goal_input" }
        guard let text = try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = ?", arguments: [key]) else { return GoalInput() }
        return try JSONDecoder().decode(GoalInput.self, from: Data(text.utf8))
    }

    private nonisolated static func loadGoalDetails(_ db: Database) throws -> GoalDetails? {
        guard let goalID = try selectedGoalID(db),
              let row = try Row.fetchOne(db, sql: "SELECT * FROM goal WHERE id = ?", arguments: [goalID]) else { return nil }
        return GoalDetails(id: goalID, statement: row["statement"], completionCriteria: row["completion_criteria"],
                           context: try loadGoalContext(db, row: row, goalID: goalID),
                           deferredActions: try deferredCards(db, goalID: goalID))
    }

    /// 선택 입력을 검사해 저장한다. 확인용 요약만 요청한다.
    public func prepareGoal() throws {
        guard screen == .goalInput else { throw ProgressFlowError.goalInputNotActive }
        let input = goalInput
        let statement = input.statement.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !statement.isEmpty else { throw ProgressFlowError.emptyGoal }
        let links = input.materialLinks.split(whereSeparator: \.isNewline).compactMap { Self.nonempty(String($0)) }
        let urls = links.compactMap(URL.init(string:))
        let minutesText = input.availableMinutes.trimmingCharacters(in: .whitespacesAndNewlines)
        let minutes = Int(minutesText)
        guard urls.count == links.count,
              urls.allSatisfy({ ["https", "http"].contains($0.scheme?.lowercased() ?? "") && !($0.host ?? "").isEmpty }),
              minutesText.isEmpty || (minutes ?? 0) > 0 else { throw ProgressFlowError.invalidGoalContext }
        try perform { db in
            if let previous = try Self.selectedGoalID(db) {
                try Self.endPendingRequests(db, goalID: previous, status: "interrupted")
            }
            let now = Date()
            try db.execute(
                sql: """
                INSERT INTO goal (statement, deadline, current_state, blocker, materials, material_excerpt, available_minutes,
                                  is_confirmed, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                arguments: [statement, Self.nonempty(input.deadline), Self.nonempty(input.currentState), Self.nonempty(input.blocker),
                            String(decoding: try JSONEncoder().encode(urls), as: UTF8.self), Self.nonempty(input.materialExcerpt), minutes, now, now]
            )
            let goalID = db.lastInsertedRowID
            try db.execute(sql: "UPDATE app_metadata SET key = ? WHERE key = 'goal_input'", arguments: ["goal_input:\(goalID)"])
            try db.execute(sql: "INSERT INTO app_metadata (key, value) VALUES ('selected_goal_id', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                           arguments: [String(goalID)])
            return try Self.insertRequest(db, goalID: goalID, kind: .goalPreparation)
        }
    }

    /// 사용자가 확인한 완료 조건만 확정한다. 그 뒤 첫 행동을 요청한다.
    public func confirmGoal(completionCriteria: String) throws {
        guard case .preparingGoal(_, .some, nil) = screen else { throw ProgressFlowError.goalNotReady }
        guard let criteria = Self.nonempty(completionCriteria) else { throw ProgressFlowError.goalNotReady }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { throw ProgressFlowError.goalNotFound }
            try db.execute(sql: "UPDATE goal SET completion_criteria = ?, is_confirmed = 1, proposed_completion_criteria = NULL WHERE id = ? AND NOT is_confirmed AND proposed_completion_criteria IS NOT NULL",
                           arguments: [criteria, goalID])
            guard db.changesCount == 1 else { throw ProgressFlowError.goalNotReady }
            try db.execute(sql: "DELETE FROM app_metadata WHERE key = ?", arguments: ["goal_input:\(goalID)"])
            try Self.bumpRevision(db, goalID: goalID)
            return try Self.insertRequest(db, goalID: goalID, kind: .firstAction)
        }
    }

    private nonisolated static func nonempty(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// 목표의 확인 질문 하나에 답한다. 답은 원래 질문과 함께 목표 맥락으로 보존한다.
    public func answerGoalQuestion(_ text: String) throws {
        guard case .preparingGoal(.some, nil, nil) = screen else { throw ProgressFlowError.goalNotReady }
        guard let answer = Self.nonempty(text) else { throw ProgressFlowError.emptyAnswer }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { throw ProgressFlowError.goalNotFound }
            try db.execute(sql: "UPDATE suggestion_request SET answer = ? WHERE id = (SELECT MAX(id) FROM suggestion_request WHERE goal_id = ?) AND kind = ? AND question IS NOT NULL AND answer IS NULL AND status = 'applied'",
                           arguments: [answer, goalID, SuggestionKind.goalPreparation.rawValue])
            guard db.changesCount == 1 else { throw ProgressFlowError.goalNotReady }
            try Self.bumpRevision(db, goalID: goalID)
            return try Self.insertRequest(db, goalID: goalID, kind: .goalPreparation)
        }
    }

    private nonisolated static func loadGoalContext(_ db: Database, row: Row, goalID: Int64) throws -> GoalContext {
        let materials: String? = row["materials"]
        return GoalContext(deadline: row["deadline"], currentState: row["current_state"],
                           materialLinks: try materials.map { try JSONDecoder().decode([URL].self, from: Data($0.utf8)) } ?? [],
                           materialExcerpt: row["material_excerpt"], availableMinutes: row["available_minutes"],
                           answers: try Row.fetchAll(db, sql: "SELECT question, answer FROM suggestion_request WHERE goal_id = ? AND kind = ? AND answer IS NOT NULL ORDER BY id",
                                                    arguments: [goalID, SuggestionKind.goalPreparation.rawValue]).map { GoalAnswer(question: $0["question"], answer: $0["answer"]) })
    }

    /// 입력 초안을 그대로 자동 저장한다. 결과나 완료 기록으로 바꾸지 않는다.
    public func updateDraft(_ text: String, for actionID: Int64) throws {
        guard case .currentAction(let card, _) = screen, card.id == actionID else {
            throw ProgressFlowError.actionNotCurrent
        }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db),
                  try Bool.fetchOne(db, sql: "SELECT EXISTS (SELECT 1 FROM action WHERE id = ? AND goal_id = ? AND status = 'current')",
                                    arguments: [actionID, goalID]) == true else {
                throw ProgressFlowError.actionNotCurrent
            }
            try db.execute(
                sql: """
                INSERT INTO action_note (action_id, body, is_draft, updated_at) VALUES (?, ?, 1, ?)
                ON CONFLICT(action_id) WHERE is_draft DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at
                """,
                arguments: [actionID, text, Date()]
            )
            return nil
        }
    }

    /// 사용자가 남긴 행동 결과를 기록하고 입력 초안을 비운다. 행동을 완료하지 않는다.
    public func recordResult(_ text: String, for actionID: Int64) throws {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw ProgressFlowError.emptyResult }
        guard case .currentAction(let card, _) = screen, card.id == actionID else {
            throw ProgressFlowError.actionNotCurrent
        }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db),
                  try Bool.fetchOne(db, sql: "SELECT EXISTS (SELECT 1 FROM action WHERE id = ? AND goal_id = ? AND status = 'current')",
                                    arguments: [actionID, goalID]) == true else {
                throw ProgressFlowError.actionNotCurrent
            }
            try db.execute(
                sql: "INSERT INTO action_note (action_id, body, is_draft, updated_at) VALUES (?, ?, 0, ?)",
                arguments: [actionID, text, Date()]
            )
            try db.execute(sql: "DELETE FROM action_note WHERE action_id = ? AND is_draft", arguments: [actionID])
            return nil
        }
    }

    /// 현재 행동만 완료한다. 이미 완료한 행동에 대한 호출은 무시한다.
    public func complete() throws {
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
    public func makeSmaller() throws {
        guard case .currentAction(_, let smaller) = screen, smaller != .waiting else { return }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            // 결과 저장에 실패해 pending으로 남은 요청을 끝낸다. 늦게 온 결과는 적용하지 않는다.
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            return try Self.insertRequest(db, goalID: goalID, kind: .smaller)
        }
    }

    /// 실제 질문의 답을 원래 요청에 저장하고 같은 종류를 한 번 요청한다. 더 작게의 답만 막힘으로 확정한다.
    public func answerQuestion(_ text: String) throws {
        switch screen {
        case .currentAction(_, .question), .actionQuestion: break
        default: return
        }
        let answer = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty else { throw ProgressFlowError.emptyAnswer }
        guard let input = suggestionInput else { throw ProgressFlowError.goalNotReady }
        try perform { db in
            let currentScreen = try Self.loadScreen(db)
            guard let goalID = try Self.selectedGoalID(db),
                  try Self.loadSuggestionInput(db, screen: currentScreen)?.requestID == input.requestID,
                  let row = try Row.fetchOne(db, sql: "SELECT r.kind FROM suggestion_request r JOIN goal g ON g.id = r.goal_id WHERE r.id = ? AND r.goal_id = ? AND r.goal_revision = g.revision AND r.status = 'applied' AND r.question IS NOT NULL AND r.answer IS NULL AND g.status = 'active'",
                                            arguments: [input.requestID, goalID]),
                  let kind = SuggestionKind(rawValue: row["kind"]), kind != .goalPreparation
            else { throw ProgressFlowError.goalNotReady }
            if kind == .smaller {
                try db.execute(sql: "UPDATE goal SET blocker = ? WHERE id = ?", arguments: [answer, goalID])
            }
            try db.execute(sql: "UPDATE suggestion_request SET answer = ? WHERE id = ?", arguments: [answer, input.requestID])
            try Self.bumpRevision(db, goalID: goalID)
            let pending = try Self.insertRequest(db, goalID: goalID, kind: kind)
            do { _ = try HTTPActionSuggestionProvider.requestBody(pending.request) }
            catch SuggestionFailure.rejected { throw ProgressFlowError.answerExceedsRequestLimit }
            return pending
        }
    }

    /// 분할 직전 행동을 현재 행동으로 되돌린다. 작은 행동은 보류로 남긴다. 행동 결과는 지우지 않는다.
    public func undoSplit() throws {
        guard case .currentAction(let card, _) = screen, let origin = card.origin else { return }
        defer {
            // 되돌린 뒤 결과를 버릴 공급자 작업은 취소한다.
            if case .currentAction(let current, _) = screen, current.id == origin.id { suggestionTask?.cancel() }
        }
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

    /// 현재 행동을 보류하고 대체 행동을 요청한다. 완료 기록을 만들지 않고 행동 결과를 지우지 않는다.
    public func deferAction() throws {
        guard case .currentAction(let card, _) = screen else { return }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            try db.execute(
                sql: "UPDATE action SET status = 'deferred' WHERE id = ? AND goal_id = ? AND status = 'current'",
                arguments: [card.id, goalID]
            )
            guard db.changesCount == 1 else { return nil }
            try Self.bumpRevision(db, goalID: goalID)
            // 보류한 행동에 대한 대기 요청은 이전 상태에 대한 요청이다.
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            return try Self.insertRequest(db, goalID: goalID, kind: .replacement)
        }
    }

    /// 보류한 행동 하나를 현재 행동으로 되돌린다. 현재 행동이 있으면 그 행동을 보류한다.
    /// 재개를 선행 조건 해결로 기록하지 않는다.
    public func resume(_ actionID: Int64) throws {
        switch screen {
        case .onHold, .currentAction: break
        default: return
        }
        defer {
            // 재개한 뒤 결과를 버릴 대체 요청 작업은 취소한다.
            if case .currentAction(let current, _) = screen, current.id == actionID { suggestionTask?.cancel() }
        }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            guard try Bool.fetchOne(
                db, sql: "SELECT EXISTS(SELECT 1 FROM action WHERE id = ? AND goal_id = ? AND status = 'deferred')",
                arguments: [actionID, goalID]
            ) == true else { throw ProgressFlowError.deferredActionNotFound }
            try db.execute(sql: "UPDATE action SET status = 'deferred' WHERE goal_id = ? AND status = 'current'", arguments: [goalID])
            try db.execute(sql: "UPDATE action SET status = 'current' WHERE id = ?", arguments: [actionID])
            try Self.bumpRevision(db, goalID: goalID)
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            return nil
        }
    }

    /// 실패·중단·취소한 제안과 대체 후보가 없는 보류 중 화면만 다시 요청한다. 기다리는 중이면 무시한다.
    public func retrySuggestion() throws {
        if case .insufficientInfo(let notice, _) = screen {
            guard let goalID = goalDetails?.id else { return }
            try perform { db in
                guard try Self.canRepropose(db, goalID: goalID, noticeID: notice.requestID) else { return nil }
                let pending = try Self.insertRequest(db, goalID: goalID, kind: notice.requestKind)
                do { _ = try HTTPActionSuggestionProvider.requestBody(pending.request) }
                catch { throw ProgressFlowError.supplementalRequestTooLarge }
                return pending
            }
            return
        }
        switch screen {
        case .onHold(_, .noAction), .onHold(_, .problem): break
        case _ where screen.suggestionProblem != nil: break
        default: return
        }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            let latest = try String.fetchOne(
                db, sql: "SELECT kind FROM suggestion_request WHERE goal_id = ? ORDER BY id DESC LIMIT 1", arguments: [goalID]
            ).flatMap(SuggestionKind.init(rawValue:))
            // 결과 저장에 실패해 pending으로 남은 요청을 끝낸다. 늦게 온 결과는 적용하지 않는다.
            try Self.endPendingRequests(db, goalID: goalID, status: "interrupted")
            // 첫 행동·다음 행동은 같은 종류로 다시 요청해 분할 원본 문맥을 유지한다.
            // 그 밖에는 현재 행동이 없을 때 대체 요청이다. 모든 요청은 보류한 행동을 제외한다.
            let kind: SuggestionKind = switch latest {
            case .goalPreparation: .goalPreparation
            case .firstAction, .nextAction, nil: try Self.hasCompletion(db, goalID: goalID) ? .nextAction : .firstAction
            case .smaller, .replacement: .replacement
            }
            let pending = try Self.insertRequest(db, goalID: goalID, kind: kind)
            if !pending.request.supplementalText.isEmpty {
                do { _ = try HTTPActionSuggestionProvider.requestBody(pending.request) }
                catch { throw ProgressFlowError.supplementalRequestTooLarge }
            }
            return pending
        }
    }

    private nonisolated static func canRepropose(_ db: Database, goalID: Int64, noticeID: Int64) throws -> Bool {
        guard try selectedGoalID(db) == goalID,
              let goal = try Row.fetchOne(db, sql: "SELECT * FROM goal WHERE id = ? AND is_confirmed AND status = 'active'", arguments: [goalID]),
              let context = try loadSupplementalContext(db, goalID: goalID),
              !context.confirmedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let notice = context.lastNotice, notice.requestID == noticeID,
              let latest = try Row.fetchOne(db, sql: "SELECT id, kind, status FROM suggestion_request WHERE goal_id = ? ORDER BY id DESC LIMIT 1", arguments: [goalID]),
              latest["id"] as Int64 == notice.requestID, latest["kind"] as String == notice.requestKind.rawValue,
              latest["status"] as String == "applied",
              try validActionContext(db, goalID: goalID, kind: notice.requestKind) else { return false }
        if notice.requestKind == .smaller {
            guard let originalID = notice.currentActionID,
                  try Int64.fetchOne(db, sql: "SELECT id FROM action WHERE goal_id = ? AND status = 'current'", arguments: [goalID]) == originalID else { return false }
        }
        return try HTTPActionSuggestionProvider.inputFingerprint(makeRequest(db, goal: goal, kind: notice.requestKind)) != notice.inputFingerprint
    }

    private nonisolated static func validActionContext(_ db: Database, goalID: Int64, kind: SuggestionKind) throws -> Bool {
        let hasCurrent = try Bool.fetchOne(db, sql: "SELECT EXISTS (SELECT 1 FROM action WHERE goal_id = ? AND status = 'current')", arguments: [goalID]) == true
        switch kind {
        case .goalPreparation: return false
        case .firstAction:
            return try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM action WHERE goal_id = ?", arguments: [goalID]) == 0
        case .smaller: return hasCurrent
        case .nextAction: return try !hasCurrent && hasCompletion(db, goalID: goalID)
        case .replacement: return try !hasCurrent && !deferredCards(db, goalID: goalID).isEmpty
        }
    }

    /// 기다리는 제안을 취소한다. 저장한 뒤 공급자 작업을 취소한다. 늦게 온 결과는 적용하지 않는다.
    public func cancelSuggestion() throws {
        guard screen.isWaitingForSuggestion else { return }
        try perform { db in
            guard let goalID = try Self.selectedGoalID(db) else { return nil }
            try Self.endPendingRequests(db, goalID: goalID, status: "cancelled")
            return nil
        }
        suggestionTask?.cancel()
    }

    /// 안내를 닫고 현재 미완료 행동으로 돌아간다. 안내는 보존하며 재실행하면 다시 복구한다.
    public func dismissInformationNotice() throws {
        guard case .insufficientInfo(let notice, _) = screen, notice.requestKind == .smaller else { return }
        let restored = try database.writer.read { try Self.loadScreen($0, hidingNotice: notice.requestID) }
        guard case .currentAction = restored else { return }
        dismissedNoticeID = notice.requestID
        screen = restored
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
        let failedID = unsavedSuggestionID
        let dismissedNoticeID = dismissedNoticeID
        let (pending, screen, input, details, goals, suggestionInput, supplementalContext) = try database.writer.write { db in
            if let failedID {
                try db.execute(
                    sql: "UPDATE suggestion_request SET status = 'failed', failure_reason = ? WHERE id = ? AND status = 'pending'",
                    arguments: [SuggestionFailure.failed.rawValue, failedID]
                )
            }
            let pending = try command(db)
            let screen = try Self.loadScreen(db, hidingNotice: dismissedNoticeID)
            return (pending, screen, try Self.loadGoalInput(db), try Self.loadGoalDetails(db), try Self.loadGoals(db), try Self.loadSuggestionInput(db, screen: screen), try Self.loadSelectedSupplementalContext(db))
        }
        unsavedSuggestionID = nil
        if self.screen != screen { timingSample = nil }
        self.screen = screen
        goalInput = input
        goalDetails = details
        self.goals = goals
        self.suggestionInput = suggestionInput
        self.supplementalContext = supplementalContext
        if let pending { start(pending) }
    }

    private func start(_ pending: PendingSuggestion) {
        let provider = provider
        suggestionTask?.cancel()
        let timing = commandStart.map { SuggestionTiming(kind: pending.request.kind, start: $0) }
        timingSample = nil
        suggestionTask = Task {
            let outcome: Result<SuggestionCandidate, SuggestionFailure>
            do {
                if !pending.request.supplementalText.isEmpty {
                    try Task.checkCancellation()
                    guard try canStartReproposal(pending) else { return }
                }
                outcome = .success(try await SuggestionTiming.$current.withValue(timing) { try await provider.suggest(pending.request) })
            } catch {
                outcome = .failure(error as? SuggestionFailure ?? .failed)
            }
            finish(pending, outcome, timing: timing)
        }
    }

    private func canStartReproposal(_ pending: PendingSuggestion) throws -> Bool {
        try database.writer.read { db in
            try Self.selectedGoalID(db) == pending.goalID && Int.fetchOne(db, sql: """
                SELECT COUNT(*) FROM suggestion_request r JOIN goal g ON g.id = r.goal_id
                WHERE r.id = ? AND r.status = 'pending' AND r.kind = ? AND g.status = 'active' AND g.is_confirmed
                  AND r.goal_revision = g.revision AND g.revision = ?
                  AND r.id = (SELECT MAX(id) FROM suggestion_request WHERE goal_id = g.id)
                """, arguments: [pending.id, pending.request.kind.rawValue, pending.revision]) == 1
                && Self.validActionContext(db, goalID: pending.goalID, kind: pending.request.kind)
        }
    }

    private func finish(_ pending: PendingSuggestion, _ outcome: Result<SuggestionCandidate, SuggestionFailure>, timing: SuggestionTiming?) {
        let applyStart = SuggestionTiming.now
        let dismissedNoticeID = dismissedNoticeID
        do {
            let (screen, input, status, isCurrentRequest, supplementalContext) = try database.writer.write { db in
                try Self.apply(db, pending, outcome)
                let screen = try Self.loadScreen(db, hidingNotice: dismissedNoticeID)
                let isCurrentRequest = try timing != nil && (Self.selectedGoalID(db) == pending.goalID && Int64.fetchOne(db, sql: "SELECT MAX(id) FROM suggestion_request WHERE goal_id = ?", arguments: [pending.goalID]) == pending.id)
                let status = timing == nil ? nil : try String.fetchOne(db, sql: "SELECT status FROM suggestion_request WHERE id = ?", arguments: [pending.id])
                return (screen, try Self.loadSuggestionInput(db, screen: screen), status, isCurrentRequest, try Self.loadSelectedSupplementalContext(db))
            }
            self.screen = screen
            suggestionInput = input
            self.supplementalContext = supplementalContext
            if let timing {
                let result: String
                if status == "failed" {
                    if case .failure(let failure) = outcome { result = failure.rawValue } else { result = "unsuitable" }
                }
                else if Task.isCancelled || status != "applied" { result = status ?? "superseded" }
                else {
                    switch outcome {
                    case .success(.action), .success(.minimalAction): result = "action"
                    case .success(.question): result = "question"
                    case .success(.goalSummary): result = "goal_summary"
                    case .success(.noAction): result = "no_action"
                    case .success(.insufficientInfo): result = "insufficient_info"
                    case .failure(let failure): result = failure.rawValue
                    }
                }
                timing.finish(result, applyStart: applyStart)
                timing.save()
                if isCurrentRequest, ["applied", "failed"].contains(status) { timingSample = timing }
            }
        } catch {
            timing?.finish("storage_failed", applyStart: applyStart)
            timing?.save()
            logger.error("Suggestion result was not saved: \(String(describing: type(of: error)), privacy: .public)")
            // 취소한 요청의 결과는 화면에 반영하지 않는다.
            guard !Task.isCancelled else { return }
            unsavedSuggestionID = pending.id
            switch screen {
            case .preparingGoal(nil, nil, nil):
                screen = .preparingGoal(question: nil, completionCriteria: nil, problem: .failure(.failed))
            case .awaitingFirstAction(let goal, nil):
                screen = .awaitingFirstAction(goal: goal, problem: .failure(.failed))
            case .awaitingNextAction(nil):
                screen = .awaitingNextAction(problem: .failure(.failed))
            case .currentAction(let card, .waiting):
                screen = .currentAction(card, smaller: .problem(.failure(.failed)))
            case .onHold(let deferred, .waiting):
                screen = .onHold(deferred: deferred, status: .problem(.failure(.failed)))
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
        guard row["revision"] == pending.revision, try selectedGoalID(db) == pending.goalID,
              try Int64.fetchOne(db, sql: "SELECT MAX(id) FROM suggestion_request WHERE goal_id = ?", arguments: [pending.goalID]) == pending.id else {
            return try finishRequest(db, pending.id, status: "interrupted", reason: nil)
        }

        let isSmaller = pending.request.kind == .smaller
        let candidate: SuggestionCandidate
        switch outcome {
        case .failure(let failure):
            return try finishRequest(db, pending.id, status: "failed", reason: failure.rawValue)
        case .success(let proposed):
            guard let accepted = CandidatePolicy.accept(proposed, for: pending.request) else {
                return try finishRequest(db, pending.id, status: "failed", reason: unsuitableReason)
            }
            candidate = accepted
        }
        var action: ProposedAction
        switch candidate {
        case .insufficientInfo(let reason):
            let notice = InformationNotice(requestID: pending.id, requestKind: pending.request.kind, goalRevision: pending.revision,
                                           inputFingerprint: try HTTPActionSuggestionProvider.inputFingerprint(pending.request),
                                           reason: reason, receivedAt: Date(),
                                           currentActionID: try Int64.fetchOne(db, sql: "SELECT id FROM action WHERE goal_id = ? AND status = 'current'", arguments: [pending.goalID]))
            var context = try loadSupplementalContext(db, goalID: pending.goalID) ?? SupplementalContext()
            context.lastNotice = notice
            try saveSupplementalContext(db, context, goalID: pending.goalID)
            return try finishRequest(db, pending.id, status: "applied", reason: nil)
        case .goalSummary(let criteria):
            try db.execute(sql: "UPDATE goal SET proposed_completion_criteria = ? WHERE id = ? AND NOT is_confirmed", arguments: [criteria, pending.goalID])
            return try finishRequest(db, pending.id, status: "applied", reason: nil)
        case .noAction:
            // 보류 중 화면을 보여준다.
            return try finishRequest(db, pending.id, status: "applied", reason: nil)
        case .question(let question):
            // 이미 답한 질문은 다시 묻지 않는다.
            let answered = try Bool.fetchOne(
                db,
                sql: "SELECT EXISTS (SELECT 1 FROM suggestion_request WHERE goal_id = ? AND question = ? AND answer IS NOT NULL)",
                arguments: [pending.goalID, question]
            ) ?? false
            guard !answered else {
                return try finishRequest(db, pending.id, status: "failed", reason: unsuitableReason)
            }
            return try db.execute(
                sql: "UPDATE suggestion_request SET status = 'applied', question = ? WHERE id = ?",
                arguments: [question, pending.id]
            )
        case .action(let proposed), .minimalAction(let proposed):
            action = proposed
        }
        // 완료한 행동을 다시 제안하면 적용하지 않는다.
        let repeated = try Bool.fetchOne(
            db,
            sql: "SELECT EXISTS (SELECT 1 FROM action WHERE goal_id = ? AND status = 'done' AND task = ?)",
            arguments: [pending.goalID, action.task]
        ) ?? false
        guard !repeated else {
            return try finishRequest(db, pending.id, status: "failed", reason: unsuitableReason)
        }
        // 분할 원본은 내용을 바꾸지 않고 `split`으로 남긴다. 남은 범위와 목표의 완료 조건을 유지한다.
        var sourceID: Int64?
        if isSmaller {
            guard let source = try Row.fetchOne(
                db, sql: "SELECT id, target_name, target_description, material_links FROM action WHERE goal_id = ? AND status = 'current'",
                arguments: [pending.goalID]
            ) else { return try finishRequest(db, pending.id, status: "interrupted", reason: nil) }
            sourceID = source["id"]
            // 같은 작업을 나눈 행동에서 생략한 대상 정보는 분할 원본의 정보를 유지한다.
            if action.targetName == nil { action.targetName = source["target_name"] }
            if action.targetName == source["target_name"] as String? {
                if action.targetDescription == nil { action.targetDescription = source["target_description"] }
                if action.materialLinks.isEmpty {
                    action.materialLinks = try JSONDecoder().decode([URL].self, from: Data((source["material_links"] as String).utf8))
                }
            }
            try db.execute(sql: "UPDATE action SET status = 'split' WHERE id = ?", arguments: [sourceID])
        }
        try db.execute(
            sql: """
            INSERT INTO action (goal_id, task, done_when, estimated_minutes, target_name, target_description, material_links, status, split_from_id, sequence)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'current', ?, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM action WHERE goal_id = ?))
            """,
            arguments: [pending.goalID, action.task, action.doneWhen, action.estimatedMinutes,
                        action.targetName, action.targetDescription, String(decoding: try JSONEncoder().encode(action.materialLinks), as: UTF8.self),
                        sourceID, pending.goalID]
        )
        try bumpRevision(db, goalID: pending.goalID)
        try finishRequest(db, pending.id, status: "applied", reason: nil)
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
        guard let goal = try Row.fetchOne(db, sql: "SELECT * FROM goal WHERE id = ?", arguments: [goalID]) else {
            throw ProgressFlowError.goalNotFound
        }
        let revision: Int = goal["revision"]
        try db.execute(sql: "DELETE FROM app_metadata WHERE key = ?", arguments: ["suggestion_input:\(goalID)"])
        try db.execute(
            sql: "INSERT INTO suggestion_request (goal_id, kind, goal_revision, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            arguments: [goalID, kind.rawValue, revision, Date()]
        )
        let requestID = db.lastInsertedRowID
        return PendingSuggestion(id: requestID, goalID: goalID, revision: revision,
                                 request: try makeRequest(db, goal: goal, kind: kind))
    }

    private nonisolated static func makeRequest(_ db: Database, goal: Row, kind: SuggestionKind) throws -> SuggestionRequest {
        let goalID: Int64 = goal["id"]
        let revision: Int = goal["revision"]
        let completed = try String.fetchAll(
            db,
            sql: """
            SELECT a.task FROM completion c JOIN action a ON a.id = c.action_id
            WHERE a.goal_id = ? ORDER BY c.id
            """,
            arguments: [goalID]
        )
        return SuggestionRequest(
            kind: kind,
            goal: goal["statement"],
            currentAction: try contextAction(db, goalID: goalID, kind: kind),
            completedTasks: completed,
            blocker: goal["blocker"],
            splitSources: kind == .smaller ? try splitSources(db, goalID: goalID) : [],
            deferredTasks: try deferredCards(db, goalID: goalID).map(\.task),
            context: try loadGoalContext(db, row: goal, goalID: goalID),
            completionCriteria: goal["completion_criteria"],
            stateKey: "\(goalID):\(revision)",
            remainingTasks: try String.fetchAll(db, sql: "SELECT task FROM action WHERE goal_id = ? AND status IN ('current', 'split', 'deferred') ORDER BY sequence", arguments: [goalID]),
            completedActionIDs: try Int64.fetchAll(db, sql: "SELECT a.id FROM completion c JOIN action a ON a.id = c.action_id WHERE a.goal_id = ? ORDER BY c.id", arguments: [goalID]).map(String.init),
            actionAnswers: try Row.fetchAll(db, sql: "SELECT question, answer FROM suggestion_request WHERE goal_id = ? AND kind != ? AND answer IS NOT NULL ORDER BY id",
                                           arguments: [goalID, SuggestionKind.goalPreparation.rawValue]).map { GoalAnswer(question: $0["question"], answer: $0["answer"]) },
            supplementalText: kind != .goalPreparation ? try loadSupplementalContext(db, goalID: goalID)?.confirmedText ?? "" : ""
        )
    }

    private nonisolated static func loadSelectedSupplementalContext(_ db: Database) throws -> SupplementalContext? {
        guard let goalID = try selectedGoalID(db) else { return nil }
        return try loadSupplementalContext(db, goalID: goalID)
    }

    private nonisolated static func saveSupplementalContext(_ db: Database, _ context: SupplementalContext, goalID: Int64) throws {
        let text = String(decoding: try JSONEncoder().encode(context), as: UTF8.self)
        try db.execute(sql: "INSERT INTO app_metadata (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                       arguments: ["supplemental_context:\(goalID)", text])
    }

    private nonisolated static func loadSupplementalContext(_ db: Database, goalID: Int64) throws -> SupplementalContext? {
        guard let text = try String.fetchOne(db, sql: "SELECT value FROM app_metadata WHERE key = ?",
                                            arguments: ["supplemental_context:\(goalID)"]) else { return nil }
        return try JSONDecoder().decode(SupplementalContext.self, from: Data(text.utf8))
    }

    private nonisolated static func deferredCards(_ db: Database, goalID: Int64) throws -> [ActionCard] {
        try Row.fetchAll(
            db,
            sql: "SELECT id, task, done_when, estimated_minutes FROM action WHERE goal_id = ? AND status = 'deferred' ORDER BY sequence",
            arguments: [goalID]
        ).map { ActionCard(id: $0["id"], task: $0["task"], doneWhen: $0["done_when"], estimatedMinutes: $0["estimated_minutes"]) }
    }

    private nonisolated static func splitSources(_ db: Database, goalID: Int64) throws -> [String] {
        try String.fetchAll(
            db,
            sql: """
            WITH RECURSIVE source(id, task, depth) AS (
                SELECT p.id, p.task, 1 FROM action a JOIN action p ON p.id = a.split_from_id
                WHERE a.goal_id = ? AND a.status = 'current'
                UNION ALL
                SELECT p.id, p.task, s.depth + 1 FROM source s
                JOIN action a ON a.id = s.id JOIN action p ON p.id = a.split_from_id
            )
            SELECT task FROM source ORDER BY depth DESC
            """,
            arguments: [goalID]
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
        case .goalPreparation, .firstAction, .replacement:
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

    private nonisolated static func loadScreen(_ db: Database, hidingNotice: Int64? = nil) throws -> ProgressScreen {
        guard let goalID = try selectedGoalID(db) else { return .goalInput }
        guard let goalRow = try Row.fetchOne(db, sql: "SELECT * FROM goal WHERE id = ?", arguments: [goalID]) else { return .goalInput }
        let stopped = goalRow["status"] as String == "stopped"
        let latest = try Row.fetchOne(
            db,
            sql: """
            SELECT id, kind, goal_revision, status, failure_reason, question, answer FROM suggestion_request
            WHERE goal_id = ? ORDER BY id DESC LIMIT 1
            """,
            arguments: [goalID]
        )
        if !(goalRow["is_confirmed"] as Bool) {
            if stopped { return .stoppedGoal(nil) }
            return .preparingGoal(question: latest?["question"], completionCriteria: goalRow["proposed_completion_criteria"],
                                  problem: latest.map(requestProblem) ?? .interrupted)
        }
        if !stopped, let latest, latest["status"] as String == "applied",
           let notice = try loadSupplementalContext(db, goalID: goalID)?.lastNotice,
           notice.requestID == latest["id"] as Int64, notice.requestID != hidingNotice {
            let fingerprint = try HTTPActionSuggestionProvider.inputFingerprint(makeRequest(db, goal: goalRow, kind: notice.requestKind))
            return .insufficientInfo(notice, isPrevious: notice.goalRevision != goalRow["revision"] as Int || notice.inputFingerprint != fingerprint)
        }
        if let row = try Row.fetchOne(
            db,
            sql: """
            SELECT a.id, a.task, a.done_when, a.estimated_minutes, a.target_name, a.target_description, a.material_links,
                   a.split_from_id, p.task AS source_task, g.revision
            FROM action a JOIN goal g ON g.id = a.goal_id
            LEFT JOIN action p ON p.id = a.split_from_id AND p.status = 'split'
            WHERE a.goal_id = ? AND a.status = 'current'
            """,
            arguments: [goalID]
        ) {
            let card = ActionCard(
                id: row["id"],
                task: row["task"],
                doneWhen: row["done_when"],
                estimatedMinutes: row["estimated_minutes"],
                // 분할 원본이 `split`일 때만 되돌릴 수 있다. 보류·완료한 원본은 관계에서 뺀다.
                origin: (row["source_task"] as String?).map { ActionCard.Origin(id: row["split_from_id"], task: $0) },
                draft: try String.fetchOne(db, sql: "SELECT body FROM action_note WHERE action_id = ? AND is_draft", arguments: [row["id"] as Int64]) ?? "",
                results: try Row.fetchAll(db, sql: "SELECT id, body FROM action_note WHERE action_id = ? AND NOT is_draft ORDER BY id",
                                          arguments: [row["id"] as Int64]).map { ActionResult(id: $0["id"], body: $0["body"]) },
                targetName: row["target_name"],
                targetDescription: row["target_description"],
                materialLinks: try JSONDecoder().decode([URL].self, from: Data((row["material_links"] as String).utf8)),
                previousResults: try Row.fetchAll(
                    db,
                    sql: """
                    SELECT n.id, n.body FROM action_note n JOIN action a ON a.id = n.action_id
                    WHERE a.goal_id = ? AND a.target_name = ? AND a.id != ? AND NOT n.is_draft ORDER BY n.id
                    """,
                    arguments: [goalID, row["target_name"] as String?, row["id"] as Int64]
                ).map { ActionResult(id: $0["id"], body: $0["body"]) }
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
            return stopped ? .stoppedGoal(card) : .currentAction(card, smaller: smaller)
        }
        if stopped { return .stoppedGoal(nil) }
        if let latest, latest["status"] as String == "applied", latest["answer"] == nil,
           latest["goal_revision"] as Int == goalRow["revision"] as Int, let question: String = latest["question"] {
            return .actionQuestion(question)
        }
        let problem: SuggestionProblem? = if let latest, latest["question"] as String? != nil,
            latest["goal_revision"] as Int != goalRow["revision"] as Int { .interrupted }
            else { latest.map(requestProblem) ?? .interrupted }
        // 보류한 행동이 있으면 어떤 요청을 기다리거나 실패해도 재개할 수 있게 보류 목록을 보여준다.
        let deferred = try deferredCards(db, goalID: goalID)
        if !deferred.isEmpty {
            let status: HoldStatus = if let problem { .problem(problem) }
                else if latest?["status"] as String? == "pending" { .waiting }
                else { .noAction }
            return .onHold(deferred: deferred, status: status)
        }
        if try hasCompletion(db, goalID: goalID) { return .awaitingNextAction(problem: problem) }
        let goal = try String.fetchOne(db, sql: "SELECT statement FROM goal WHERE id = ?", arguments: [goalID]) ?? ""
        return .awaitingFirstAction(goal: goal, problem: problem)
    }
}

extension ProgressScreen {
    /// 제안을 기다리는 중인지 나타낸다.
    var isWaitingForSuggestion: Bool {
        switch self {
        case .preparingGoal(nil, nil, nil): true
        case .awaitingFirstAction(_, nil), .awaitingNextAction(nil), .currentAction(_, .waiting), .onHold(_, .waiting): true
        default: false
        }
    }

    /// 실패·중단·취소한 제안의 문제다. '다시 시도'를 보여줄 때만 값이 있다.
    var suggestionProblem: SuggestionProblem? {
        switch self {
        case .preparingGoal(_, _, let problem): problem
        case .awaitingFirstAction(_, let problem), .awaitingNextAction(let problem): problem
        case .onHold(_, .problem(let problem)): problem
        case .goalInput, .currentAction, .onHold, .stoppedGoal, .insufficientInfo, .actionQuestion: nil
        }
    }
}

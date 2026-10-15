import Foundation

/// 진행 흐름 모듈이 주입받는 행동 제안 공급자 경계다.
/// 구현은 자동 재시도를 하지 않는다. 취소는 Swift Task 취소로 전달한다.
public protocol ActionSuggestionProvider: Sendable {
    /// 후보 하나를 반환한다. 실패하면 `SuggestionFailure`를 던진다.
    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate
}

public enum SuggestionKind: String, Sendable {
    case goalPreparation = "goal_preparation"
    case firstAction = "first_action"
    case nextAction = "next_action"
    case smaller
    case replacement
}

public struct SuggestionRequest: Sendable, Equatable {
    var kind: SuggestionKind
    var goal: String
    var currentAction: ProposedAction?
    /// 완료한 행동의 할 일. 오래된 것부터 담는다.
    var completedTasks: [String]
    /// 사용자가 알려준 막힘 원인이다. 같은 정보를 다시 묻지 않게 한다.
    var blocker: String? = nil
    /// 더 작게 요청에서 현재 행동을 나눈 분할 원본의 할 일. 가장 처음 원본부터 담는다.
    /// 비어 있지 않으면 같은 작업을 이미 나눴다. 공급자는 이 값으로 반복 막힘을 판단한다.
    var splitSources: [String] = []
    /// 보류한 행동의 할 일. 생성 순서로 담는다. 공급자는 이 행동을 다시 제안하지 않는다.
    var deferredTasks: [String] = []
    var context = GoalContext()
    var completionCriteria: String? = nil
    /// 같은 목표 리비전의 HTTP 중복 요청을 막는 키다.
    var stateKey: String = ""
    /// 완료한 행동과 구분하는 미완료 분할 원본·현재·보류 행동이다.
    var remainingTasks: [String] = []
    var completedActionIDs: [String] = []
}

public struct GoalAnswer: Equatable, Sendable {
    let question: String
    let answer: String
}

/// 자료 본문을 자동으로 읽지 않는다. 링크와 사용자가 고른 발췌·요약만 담는다.
public struct GoalContext: Equatable, Sendable {
    var deadline: String? = nil
    public var currentState: String? = nil
    var materialLinks: [URL] = []
    var materialExcerpt: String? = nil
    var availableMinutes: Int? = nil
    var answers: [GoalAnswer] = []
}

public struct ProposedAction: Sendable, Equatable {
    var task: String
    var doneWhen: String
    var estimatedMinutes: Int
    var targetName: String? = nil
    var targetDescription: String? = nil
    var materialLinks: [URL] = []
    /// 공급자가 목표 완료를 표시했는지 나타낸다. 앱은 이 표시로 목표를 완료하지 않는다.
    var marksGoalComplete = false
    /// 공급자가 원래 행동의 완료를 표시했는지 나타낸다. 앱은 이 표시로 행동을 완료하지 않는다.
    var marksCurrentActionComplete = false
}

public enum SuggestionCandidate: Sendable, Equatable {
    /// 사용자가 확인하기 전에는 목표의 완료 조건으로 저장하지 않는다.
    case goalSummary(String)
    case action(ProposedAction)
    case question(String)
    case minimalAction(ProposedAction)
    /// 선행 조건이 준비된 다른 행동이 없다. 대체 요청에서만 쓴다.
    case noAction
}

public enum SuggestionFailure: String, Error, Sendable, CaseIterable {
    case connectionLost = "connection_lost"
    case rejected
    case undecidable
    case failed
    case timedOut = "timed_out"
    case budgetLimit = "budget_limit"
    case unavailable
}

/// 요청 종류에 맞고 바로 보여줄 수 있는 후보만 받는다. 앞뒤 공백을 지운 후보를 돌려준다.
/// 공급자와 관계없는 규칙이다. 저장된 기록이 필요한 검사는 `ProgressFlow`가 한다.
public enum CandidatePolicy {
    static func accept(_ candidate: SuggestionCandidate, for request: SuggestionRequest) -> SuggestionCandidate? {
        switch candidate {
        case .goalSummary(let text):
            guard request.kind == .goalPreparation, let criteria = trimmed(text) else { return nil }
            return .goalSummary(criteria)
        case .noAction:
            // 대체 후보 없음은 대체 요청에서만 받는다.
            return request.kind == .replacement ? .noAction : nil
        case .question(let text):
            // 목표 준비와 더 작게에서만 확인 질문 하나를 받는다.
            guard request.kind == .goalPreparation || request.kind == .smaller, let question = trimmed(text) else { return nil }
            return .question(question)
        case .action(let proposed):
            return action(proposed, for: request).map(SuggestionCandidate.action)
        case .minimalAction(let proposed):
            return action(proposed, for: request).map(SuggestionCandidate.minimalAction)
        }
    }

    /// 필수 필드가 비었거나 목표·원래 행동의 완료를 표시한 후보는 받지 않는다.
    /// 더 작게는 현재 행동을, 다른 요청은 보류한 행동을 그대로 다시 제안하면 받지 않는다.
    /// 더 작게는 되돌린 작은 행동을 다시 제안할 수 있다(#55).
    private static func action(_ proposed: ProposedAction, for request: SuggestionRequest) -> ProposedAction? {
        guard request.kind != .goalPreparation, let task = trimmed(proposed.task), let doneWhen = trimmed(proposed.doneWhen),
              proposed.estimatedMinutes > 0, !proposed.marksGoalComplete, !proposed.marksCurrentActionComplete,
              proposed.materialLinks.allSatisfy({ ["https", "http"].contains($0.scheme?.lowercased() ?? "") && !($0.host ?? "").isEmpty })
        else { return nil }
        let excluded = request.kind == .smaller ? [request.currentAction?.task].compactMap { $0 } : request.deferredTasks
        guard !excluded.contains(task) else { return nil }
        var action = proposed
        action.task = task
        action.doneWhen = doneWhen
        action.targetName = proposed.targetName.flatMap(trimmed)
        action.targetDescription = proposed.targetDescription.flatMap(trimmed)
        return action
    }

    private static func trimmed(_ text: String) -> String? {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }
}

/// 실제 공급자를 연결하기 전에 쓰는 공급자다. 항상 `사용 불가`를 반환한다.
public struct UnavailableSuggestionProvider: ActionSuggestionProvider {
    public init() {}

    public func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        throw SuggestionFailure.unavailable
    }
}

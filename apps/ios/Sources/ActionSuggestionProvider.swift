import Foundation

/// 진행 흐름 모듈이 주입받는 행동 제안 공급자 경계다.
/// 구현은 자동 재시도를 하지 않는다. 취소는 Swift Task 취소로 전달한다.
protocol ActionSuggestionProvider: Sendable {
    /// 후보 하나를 반환한다. 실패하면 `SuggestionFailure`를 던진다.
    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate
}

enum SuggestionKind: String, Sendable {
    case firstAction = "first_action"
    case nextAction = "next_action"
    case smaller
    case replacement
}

struct SuggestionRequest: Sendable, Equatable {
    var kind: SuggestionKind
    var goal: String
    var currentAction: ProposedAction?
    /// 완료한 행동의 할 일. 오래된 것부터 담는다.
    var completedTasks: [String]
}

struct ProposedAction: Sendable, Equatable {
    var task: String
    var doneWhen: String
    var estimatedMinutes: Int
    /// 공급자가 목표 완료를 표시했는지 나타낸다. 앱은 이 표시로 목표를 완료하지 않는다.
    var marksGoalComplete = false
}

enum SuggestionCandidate: Sendable, Equatable {
    case action(ProposedAction)
    case question(String)
    case minimalAction(ProposedAction)
}

enum SuggestionFailure: String, Error, Sendable {
    case rejected
    case undecidable
    case failed
    case timedOut = "timed_out"
    case budgetLimit = "budget_limit"
    case unavailable
}

/// 실제 공급자를 연결하기 전에 쓰는 공급자다. 항상 `사용 불가`를 반환한다.
struct UnavailableSuggestionProvider: ActionSuggestionProvider {
    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        throw SuggestionFailure.unavailable
    }
}

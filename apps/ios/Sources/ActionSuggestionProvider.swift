import Foundation

/// 진행 흐름 모듈이 주입받는 행동 제안 공급자 경계다.
/// 구현은 자동 재시도를 하지 않는다. 취소는 Swift Task 취소로 전달한다.
protocol ActionSuggestionProvider: Sendable {
    /// 후보 하나를 반환한다. 실패하면 `SuggestionFailure`를 던진다.
    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate
}

enum SuggestionKind: String, Sendable {
    case goalPreparation = "goal_preparation"
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

struct GoalAnswer: Equatable, Sendable {
    let question: String
    let answer: String
}

/// 자료 본문을 자동으로 읽지 않는다. 링크와 사용자가 고른 발췌·요약만 담는다.
struct GoalContext: Equatable, Sendable {
    var deadline: String? = nil
    var currentState: String? = nil
    var materialLinks: [URL] = []
    var materialExcerpt: String? = nil
    var availableMinutes: Int? = nil
    var answers: [GoalAnswer] = []
}

struct ProposedAction: Sendable, Equatable {
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

enum SuggestionCandidate: Sendable, Equatable {
    /// 사용자가 확인하기 전에는 목표의 완료 조건으로 저장하지 않는다.
    case goalSummary(String)
    case action(ProposedAction)
    case question(String)
    case minimalAction(ProposedAction)
    /// 선행 조건이 준비된 다른 행동이 없다. 대체 요청에서만 쓴다.
    case noAction
}

enum SuggestionFailure: String, Error, Sendable, CaseIterable {
    case connectionLost = "connection_lost"
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

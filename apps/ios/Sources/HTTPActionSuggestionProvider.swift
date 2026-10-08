import Foundation

/// 기존 입력·응답 계약을 개발·사용자용 공급자가 공유한다.
struct HTTPActionSuggestionProvider: ActionSuggestionProvider {
    let baseURL: URL
    let path: String
    let token: @Sendable () async throws -> String?
    var rejectCompletion = false
    var session: URLSession = .shared
    var timeout: TimeInterval = 130

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        try Task.checkCancellation()
        guard (request.blocker?.utf8.count ?? 0) <= 2048 else { throw SuggestionFailure.rejected }
        let input = Input(request)
        let bytes = try JSONEncoder().encode(Payload(state_key: request.stateKey, input: input))
        guard bytes.count <= 32 * 1024 else { throw SuggestionFailure.rejected }
        var http = URLRequest(url: baseURL.appendingPathComponent(path))
        http.httpMethod = "POST"
        http.httpBody = bytes
        http.timeoutInterval = timeout
        http.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let token = try await token()
        try Task.checkCancellation()
        if let token, !token.isEmpty { http.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: http, delegate: NoRedirect())
        } catch {
            if Task.isCancelled { throw CancellationError() }
            if let error = error as? URLError {
                switch error.code {
                case .cancelled: throw CancellationError()
                case .timedOut: throw SuggestionFailure.timedOut
                case .notConnectedToInternet, .networkConnectionLost, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed:
                    throw SuggestionFailure.connectionLost
                default: throw SuggestionFailure.failed
                }
            }
            throw SuggestionFailure.failed
        }
        try Task.checkCancellation()
        guard let response = response as? HTTPURLResponse else { throw SuggestionFailure.failed }
        switch response.statusCode {
        case 200: break
        case 401, 403, 400, 413: throw SuggestionFailure.rejected
        case 429: throw SuggestionFailure.budgetLimit
        case 408, 504: throw SuggestionFailure.timedOut
        case 409: throw SuggestionFailure.unavailable
        default: throw SuggestionFailure.failed
        }
        guard data.count <= 128 * 1024, let result = try? JSONDecoder().decode(Result.self, from: data)
        else { throw SuggestionFailure.failed }
        switch result.disposition {
        case "accepted": break
        case "rejected", "invalid_input", "invalid_proposal": throw SuggestionFailure.rejected
        case "uncertain": throw SuggestionFailure.undecidable
        case "timed_out": throw SuggestionFailure.timedOut
        case "budget_limit": throw SuggestionFailure.budgetLimit
        case "connection_lost": throw SuggestionFailure.connectionLost
        case "disabled", "busy", "superseded": throw SuggestionFailure.unavailable
        default: throw SuggestionFailure.failed
        }
        guard let proposal = result.proposal,
              proposal.remaining_work == input.remaining_work,
              proposal.preserved_completed_ids == input.completed_ids,
              proposal.estimated_minutes.isFinite, proposal.estimated_minutes >= 0,
              proposal.estimated_minutes < Double(Int.max),
              proposal.estimated_minutes <= input.available_minutes,
              !proposal.action.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !proposal.completion_condition.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { throw SuggestionFailure.rejected }
        if rejectCompletion && (proposal.goal_completed || proposal.current_action_completed) { throw SuggestionFailure.rejected }
        let action = ProposedAction(task: proposal.action, doneWhen: proposal.completion_condition,
                                    estimatedMinutes: Int(proposal.estimated_minutes.rounded(.up)),
                                    marksGoalComplete: proposal.goal_completed,
                                    marksCurrentActionComplete: proposal.current_action_completed)
        switch proposal.status {
        case "action": return .action(action)
        case "minimum": return .minimalAction(action)
        case "need_info":
            guard !proposal.goal_completed, !proposal.current_action_completed else { throw SuggestionFailure.rejected }
            return .question(proposal.action)
        case "goal_summary" where request.kind == .goalPreparation:
            guard !proposal.goal_completed, !proposal.current_action_completed else { throw SuggestionFailure.rejected }
            return .goalSummary(proposal.completion_condition)
        case "no_action" where request.kind == .replacement:
            guard !proposal.goal_completed, !proposal.current_action_completed else { throw SuggestionFailure.rejected }
            return .noAction
        default: throw SuggestionFailure.rejected
        }
    }

    private struct Payload: Encodable { let state_key: String; let input: Input }
    private struct Input: Encodable {
        let goal: String
        let current_blocker: String
        let user_request: String
        let available: [String]
        let unknown: [String]
        let available_minutes: Double
        let knowledge = "사용자가 제공한 정보 외에는 모름"
        let energy = "모름"
        let remaining_work: [String]
        let completed_ids: [String]
        let previous_proposals: [Proposal]
        let request_kind: String

        init(_ request: SuggestionRequest) {
            goal = request.goal
            current_blocker = request.blocker ?? ""
            request_kind = request.kind.rawValue
            switch request.kind {
            case .goalPreparation: user_request = "최종 목표의 관찰 가능한 완료 조건을 제안한다. 사용자가 확인하기 전에는 확정하지 않는다."
            case .firstAction: user_request = "지금 시작할 첫 행동 하나를 제안한다."
            case .nextAction: user_request = "완료한 행동을 반복하지 않고 남은 범위의 다음 행동 하나를 제안한다."
            case .smaller: user_request = "현재 행동을 실질적으로 줄인다. 반복 막힘이면 알려진 답을 다시 묻지 않고 첫 막힘 한 가지를 확인한다."
            case .replacement: user_request = "보류한 행동과 다른 준비된 행동 하나를 제안한다. 없으면 no_action을 반환한다."
            }
            var facts: [String] = []
            if let criteria = request.completionCriteria { facts.append("확정 완료 조건: \(criteria)") }
            if let text = request.context.currentState { facts.append("현재 상태: \(text)") }
            if let text = request.context.deadline { facts.append("기한: \(text)") }
            if let text = request.context.materialExcerpt { facts.append("사용자가 선택한 자료 발췌: \(text)") }
            facts += request.context.materialLinks.map { "자료 링크(본문을 읽지 않음): \($0.absoluteString)" }
            facts += request.context.answers.map { "이미 답한 질문: \($0.question) / 답: \($0.answer)" }
            facts += request.completedTasks.map { "이미 완료한 행동: \($0)" }
            facts += request.deferredTasks.map { "보류한 행동(재제안 금지): \($0)" }
            available = facts
            unknown = []
            available_minutes = Double(request.context.availableMinutes ?? 15)
            let remaining = [request.completionCriteria ?? request.goal] + request.remainingTasks
            let completed = request.completedActionIDs
            remaining_work = remaining
            completed_ids = completed
            var earlier = request.splitSources.map { task in
                Proposal(status: "action", action: task, completion_condition: "원본 범위를 아직 완료하지 않음", estimated_minutes: 0,
                         reason: "미완료 분할 원본", remaining_work: remaining, goal_completed: false,
                         current_action_completed: false, preserved_completed_ids: completed)
            }
            if request.kind == .smaller, let current = request.currentAction {
                earlier.append(Proposal(status: "action", action: current.task, completion_condition: current.doneWhen,
                                        estimated_minutes: Double(current.estimatedMinutes), reason: "현재 미완료 행동",
                                        remaining_work: remaining_work, goal_completed: false,
                                        current_action_completed: false, preserved_completed_ids: completed_ids))
            }
            previous_proposals = earlier
        }
    }
    private struct Result: Decodable { let disposition: String; let proposal: Proposal? }
    private struct Proposal: Codable {
        let status: String
        let action: String
        let completion_condition: String
        let estimated_minutes: Double
        let reason: String
        let remaining_work: [String]
        let goal_completed: Bool
        let current_action_completed: Bool
        let preserved_completed_ids: [String]
    }

    private final class NoRedirect: NSObject, URLSessionTaskDelegate {
        func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                        newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
            completionHandler(nil)
        }
    }
}

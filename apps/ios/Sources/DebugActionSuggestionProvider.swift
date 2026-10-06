#if DEBUG
import Foundation

struct DebugActionSuggestionProvider: ActionSuggestionProvider {
    let delay: Duration

    init(delay: Duration = .milliseconds(400)) {
        self.delay = delay
    }

    static let exampleGoals: [String] = examples.map(\.goal)
    private static let smallerPrefix = "첫 부분만: "

    func suggest(_ request: SuggestionRequest) async throws -> SuggestionCandidate {
        try await Task.sleep(for: delay)
        // 더 작게: 이미 나눈 행동을 막힘 원인 없이 다시 나누면 확인 질문을 돌려준다.
        if request.kind == .smaller, let current = request.currentAction {
            if request.blocker == nil, current.task.hasPrefix(Self.smallerPrefix) {
                return .question("가장 먼저 막히는 지점은 무엇인가요?")
            }
            return .action(Self.step(Self.smallerPrefix + current.task, "첫 부분 하나를 끝낸다", max(1, current.estimatedMinutes / 2)))
        }
        let count = request.completedTasks.count
        let steps = Self.examples.first { $0.goal == request.goal }?.steps ?? Self.general
        let action = count < steps.count ? steps[count] : Self.continued(count)
        return .action(action)
    }

    private static func step(_ task: String, _ doneWhen: String, _ minutes: Int) -> ProposedAction {
        ProposedAction(task: task, doneWhen: doneWhen, estimatedMinutes: minutes, marksGoalComplete: false)
    }

    private static func continued(_ count: Int) -> ProposedAction {
        step("다음 한 가지 고르기 (\(count))", "다음 한 가지가 한 줄로 남는다", 5)
    }

    private static let general: [ProposedAction] = [
        step("목표와 관련된 첫 자료 하나 열기", "자료가 화면에 열린다", 3),
        step("연 자료에서 지금 할 한 가지를 고르기", "고른 한 가지가 한 줄로 남는다", 5),
        step("고른 한 가지를 짧게 실행하기", "실행을 마친다", 10),
        step("실행한 결과를 한 줄로 남기기", "결과 한 줄이 남는다", 5),
    ]

    private static let examples: [(goal: String, steps: [ProposedAction])] = [
        (
            "이력서 정리하기",
            [
                step("이력서 파일 하나 열기", "파일이 화면에 보인다", 3),
                step("최근 경력 한 항목의 기간 확인하기", "기간을 확인했다", 5),
                step("그 경력 설명에서 한 문장 고치기", "고친 문장이 남는다", 12),
                step("고친 이력서 저장하기", "저장이 끝난다", 2),
            ]
        ),
        (
            "분기 업무 보고서 초안 쓰기",
            [
                step("업무 보고서 문서 하나 열기", "문서가 화면에 보인다", 3),
                step("이번 분기에 끝낸 업무 하나 적기", "업무 이름이 한 줄 남는다", 8),
                step("그 업무의 결과를 한 문장으로 적기", "결과 문장이 한 줄 남는다", 10),
                step("적은 문장을 문서에 저장하기", "저장이 끝난다", 2),
            ]
        ),
        (
            "통계 기초 단원 하나 학습하기",
            [
                step("학습 자료에서 다음 단원 열기", "단원이 화면에 보인다", 3),
                step("그 단원의 첫 소제목 읽기", "소제목을 읽었다", 8),
                step("기억할 한 문장 적기", "문장 한 줄이 남는다", 10),
                step("그 문장을 다시 볼 곳에 두기", "문장이 그 위치에 있다", 4),
            ]
        ),
        (
            "개인 프로젝트로 베란다 화분 옮겨 심기",
            [
                step("옮길 화분 하나 정하기", "화분 하나가 정해진다", 3),
                step("새 자리와 흙이 있는지 확인하기", "자리와 흙의 유무를 확인했다", 5),
                step("화분을 새 자리로 옮기기", "화분이 새 자리에 있다", 12),
                step("옮긴 뒤 상태를 한 줄로 남기기", "상태 한 줄이 남는다", 4),
            ]
        ),
    ]
}
#endif

import SwiftUI

enum Motion {
    static let nextCard: Double = 0.18
}

@MainActor
struct CoreFlowView: View {
    let flow: ProgressFlow

    @State private var goalText = ""
    @State private var storageFailed = false

    private let accent = Color(red: 0.18, green: 0.27, blue: 0.16)

    private var trimmedGoal: String {
        goalText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Smallnext")
                    .font(.headline)
                    .accessibilityAddTraits(.isHeader)

                // 상태별 뷰를 위쪽에 맞춰 교체한다. 이동 없이 투명도 전환만 쓴다.
                ZStack(alignment: .topLeading) {
                    screenContent
                        .id(screenIdentity)
                        .transition(.opacity)
                }
                .animation(.easeInOut(duration: Motion.nextCard), value: screenIdentity)

                if storageFailed {
                    Text("저장하지 못했어요. 다시 시도해 주세요.")
                        .font(.body)
                        .foregroundStyle(.primary)
                }
            }
            .padding(24)
            .frame(maxWidth: 560, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color(.systemGroupedBackground))
        .tint(accent)
        .onChange(of: flow.screen) { oldScreen, newScreen in
            announceChange(from: oldScreen, to: newScreen)
        }
    }

    private var screenIdentity: String {
        switch flow.screen {
        case .goalInput: "goalInput"
        case .awaitingFirstAction: "awaitingFirstAction"
        case .currentAction(let card): "currentAction-\(card.id)"
        case .awaitingNextAction: "awaitingNextAction"
        case .suggestionFailed(let problem): "suggestionFailed-\(reason(for: problem))"
        }
    }

    @ViewBuilder
    private var screenContent: some View {
        switch flow.screen {
        case .goalInput:
            VStack(alignment: .leading, spacing: 16) {
                Text("목표를 한 문장으로 적어 주세요.")
                    .font(.title2.bold())
                    .accessibilityAddTraits(.isHeader)
                TextField("목표 한 문장", text: $goalText, axis: .vertical)
                    .font(.body)
                    .padding(16)
                    .frame(minHeight: 44)
                    .background(Color(.secondarySystemGroupedBackground),
                                in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityLabel("목표 한 문장")
                commandButton("시작") {
                    try flow.createGoal(trimmedGoal)
                }
                .disabled(trimmedGoal.isEmpty)
            }
        case .awaitingFirstAction:
            waiting("첫 행동을 준비하고 있어요.")
        case .currentAction(let card):
            actionCard(card)
                .id(card.id)
                .transition(.opacity)
        case .awaitingNextAction:
            waiting("다음 행동을 준비하고 있어요.")
        case .suggestionFailed(let problem):
            VStack(alignment: .leading, spacing: 16) {
                Text(reason(for: problem))
                    .font(.body)
                commandButton("다시 시도") {
                    try flow.retrySuggestion()
                }
            }
        }
    }

    private func actionCard(_ card: ActionCard) -> some View {
        VStack(alignment: .leading, spacing: 24) {
            Text("지금 할 행동")
                .font(.title2.bold())
                .accessibilityAddTraits(.isHeader)

            VStack(alignment: .leading, spacing: 24) {
                Label("약 \(card.estimatedMinutes)분 · 예상", systemImage: "clock")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Text(card.task)
                    .font(.title2.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                Divider()
                VStack(alignment: .leading, spacing: 8) {
                    Text("완료 조건")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text(card.doneWhen)
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemGroupedBackground),
                        in: RoundedRectangle(cornerRadius: 18))
            .overlay {
                RoundedRectangle(cornerRadius: 18)
                    .strokeBorder(Color(.separator), lineWidth: 1)
            }
            .shadow(color: accent.opacity(0.10), radius: 0, x: 0, y: 5)

            commandButton("완료") {
                try flow.complete()
            }
        }
    }

    private func waiting(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            ProgressView()
                .accessibilityLabel(message)
            Text(message)
                .font(.body)
        }
    }

    private func commandButton(
        _ title: String, command: @escaping @MainActor () throws -> Void
    ) -> some View {
        Button {
            storageFailed = false
            do {
                try withAnimation(.easeInOut(duration: Motion.nextCard)) {
                    try command()
                }
            } catch {
                storageFailed = true
                AccessibilityNotification.Announcement(
                    "저장하지 못했어요. 다시 시도해 주세요."
                ).post()
            }
        } label: {
            Text(title)
                .font(.headline)
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.borderedProminent)
    }

    private func reason(for problem: SuggestionProblem) -> String {
        switch problem {
        case .unsuitable:
            "알맞은 행동을 찾지 못했어요."
        case .interrupted:
            "행동 제안이 중단됐어요."
        case .failure(let failure):
            switch failure {
            case .rejected:
                "행동 제안 요청이 거절됐어요."
            case .undecidable:
                "다음 행동을 정하지 못했어요."
            case .failed:
                "행동을 준비하지 못했어요."
            case .timedOut:
                "행동 제안 시간이 초과됐어요."
            case .budgetLimit:
                "행동 제안 사용 한도에 도달했어요."
            case .unavailable:
                "지금은 행동 제안을 사용할 수 없어요."
            }
        }
    }

    private func announceChange(from oldScreen: ProgressScreen, to newScreen: ProgressScreen) {
        var messages: [String] = []
        if case .currentAction = oldScreen, oldScreen != newScreen {
            messages.append("행동을 완료했어요.")
        }
        switch newScreen {
        case .currentAction(let card):
            messages.append("지금 할 행동: \(card.task)")
        case .awaitingFirstAction:
            messages.append("첫 행동을 준비하고 있어요.")
        case .awaitingNextAction:
            messages.append("다음 행동을 준비하고 있어요.")
        case .suggestionFailed(let problem):
            messages.append(reason(for: problem))
        case .goalInput:
            break
        }
        if !messages.isEmpty {
            AccessibilityNotification.Announcement(messages.joined(separator: " ")).post()
        }
    }
}

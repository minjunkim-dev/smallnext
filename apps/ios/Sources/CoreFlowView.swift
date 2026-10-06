import SwiftUI

enum Motion {
    static let nextCard: Double = 0.18
    /// 분할 전환 시간이다. 실제 휴대폰에서 이 값 하나로 조정한다.
    static let split: Double = 0.34
}

@MainActor
struct CoreFlowView: View {
    let flow: ProgressFlow

    @State private var goalText = ""
    @State private var answerText = ""
    @State private var storageFailed = false
    /// 분할 직전 행동의 할 일이다. 값이 있는 동안 나뉘는 움직임을 보여준다.
    @State private var splitGhost: SplitGhost?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

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
            // 답 입력은 지금 보이는 질문에만 쓴다.
            answerText = ""
            startSplitMotion(from: oldScreen, to: newScreen)
            announceChange(from: oldScreen, to: newScreen)
        }
    }

    private var screenIdentity: String {
        switch flow.screen {
        case .goalInput: "goalInput"
        case .awaitingFirstAction(_, let problem): "awaitingFirstAction-\(String(describing: problem))"
        case .currentAction(let card, _): "currentAction-\(card.id)"
        case .awaitingNextAction(let problem): "awaitingNextAction-\(String(describing: problem))"
        case .onHold(_, let status): "onHold-\(String(describing: status))"
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
        case .awaitingFirstAction(let goal, let problem):
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("입력한 목표")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text(goal)
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
                suggestionStatus("첫 행동을 준비하고 있어요.", problem: problem)
            }
        case .currentAction(let card, let smaller):
            actionCard(card, smaller: smaller)
                .id(card.id)
                .transition(.opacity)
        case .awaitingNextAction(let problem):
            VStack(alignment: .leading, spacing: 16) {
                Text("다음 행동 대기")
                    .font(.title2.bold())
                    .accessibilityAddTraits(.isHeader)
                suggestionStatus("다음 행동을 준비하고 있어요.", problem: problem)
            }
        case .onHold(let deferred, let status):
            onHold(deferred, status: status)
        }
    }

    /// 대체 행동을 기다리거나 받지 못한 상태와 보류한 행동 목록을 보여준다. 각 행동은 '재개'할 수 있다.
    private func onHold(_ deferred: [ActionCard], status: HoldStatus) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(status == .noAction ? "보류 중" : "다른 행동 대기")
                .font(.title2.bold())
                .accessibilityAddTraits(.isHeader)
            switch status {
            case .waiting:
                suggestionStatus("다른 행동을 준비하고 있어요.", problem: nil)
            case .problem(let problem):
                suggestionStatus("다른 행동을 준비하고 있어요.", problem: problem)
            case .noAction:
                Text("지금 할 수 있는 다른 행동이 없어요. 보류한 행동을 재개하거나 다른 행동을 다시 찾아요.")
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
                commandButton("다른 행동 다시 찾기", prominent: false) {
                    try flow.retrySuggestion()
                }
            }
            Text("보류한 행동")
                .font(.headline)
                .accessibilityAddTraits(.isHeader)
                .padding(.top, 8)
            ForEach(deferred) { action in
                VStack(alignment: .leading, spacing: 12) {
                    Text(action.task)
                        .font(.body.weight(.semibold))
                        .fixedSize(horizontal: false, vertical: true)
                    Text("완료 조건: \(action.doneWhen)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    commandButton("재개", prominent: false) {
                        try flow.resume(action.id)
                    }
                    .accessibilityLabel("재개: \(action.task)")
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    private func actionCard(_ card: ActionCard, smaller: SmallerStatus?) -> some View {
        VStack(alignment: .leading, spacing: 24) {
            HStack {
                Text("지금 할 행동")
                    .font(.title2.bold())
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Menu {
                    if card.origin != nil {
                        Button("되돌리기") {
                            run { try flow.undoSplit() }
                        }
                    }
                    Button("나중에") {
                        run { try flow.deferAction() }
                    }
                } label: {
                    Label("더 보기", systemImage: "ellipsis.circle")
                        .labelStyle(.iconOnly)
                        .font(.title2)
                        .frame(minWidth: 44, minHeight: 44)
                }
            }

            if let origin = card.origin {
                Text("‘\(origin.task)’의 일부예요. 같은 작업의 남은 범위는 그대로 두었어요.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

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
            .overlay {
                if let splitGhost, !reduceMotion {
                    SplitGhostView(ghost: splitGhost) { self.splitGhost = nil }
                }
            }

            // '완료'의 위치는 더 작게 상태와 관계없이 고정한다.
            commandButton("완료") {
                try flow.complete()
            }
            smallerSection(smaller)
        }
    }

    /// 더 작게를 기다리면 '취소'를, 질문이면 답 입력을 보여준다.
    /// 문제가 있으면 짧은 이유와 다시 시도인 '더 작게'를 보여준다.
    @ViewBuilder
    private func smallerSection(_ smaller: SmallerStatus?) -> some View {
        switch smaller {
        case nil:
            smallerButton
        case .waiting:
            HStack(spacing: 12) {
                ProgressView()
                Text("더 쉬운 행동을 준비하고 있어요.")
                    .font(.body)
            }
            .accessibilityElement(children: .combine)
            commandButton("취소", prominent: false) {
                try flow.cancelSuggestion()
            }
        case .question(let question):
            VStack(alignment: .leading, spacing: 12) {
                Text(question)
                    .font(.body.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
                TextField("가장 먼저 막히는 지점", text: $answerText, axis: .vertical)
                    .font(.body)
                    .padding(16)
                    .frame(minHeight: 44)
                    .background(Color(.secondarySystemGroupedBackground),
                                in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityLabel(question)
                commandButton("답하기") {
                    try flow.answerQuestion(answerText)
                }
                .disabled(answerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        case .problem(let problem):
            Text(reason(for: problem))
                .font(.body)
            smallerButton
        }
    }

    private var smallerButton: some View {
        commandButton("더 작게", prominent: false) {
            try flow.makeSmaller()
        }
    }

    /// 기다리는 중이면 '취소'를, 문제가 있으면 짧은 이유와 '다시 시도'를 보여준다.
    @ViewBuilder
    private func suggestionStatus(_ waitingMessage: String, problem: SuggestionProblem?) -> some View {
        if let problem {
            Text(reason(for: problem))
                .font(.body)
            commandButton("다시 시도") {
                try flow.retrySuggestion()
            }
        } else {
            ProgressView()
                .accessibilityLabel(waitingMessage)
            Text(waitingMessage)
                .font(.body)
            commandButton("취소", prominent: false) {
                try flow.cancelSuggestion()
            }
        }
    }

    private func run(_ command: @MainActor () throws -> Void) {
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
    }

    @ViewBuilder
    private func commandButton(
        _ title: String, prominent: Bool = true, command: @escaping @MainActor () throws -> Void
    ) -> some View {
        let button = Button {
            run(command)
        } label: {
            Text(title)
                .font(.headline)
                .frame(maxWidth: .infinity, minHeight: 44)
        }

        if prominent {
            button.buttonStyle(.borderedProminent)
        } else {
            button.buttonStyle(.bordered)
        }
    }

    private func reason(for problem: SuggestionProblem) -> String {
        switch problem {
        case .unsuitable:
            "알맞은 행동을 찾지 못했어요."
        case .interrupted:
            "행동 제안이 중단됐어요."
        case .cancelled:
            "행동 제안을 취소했어요."
        case .failure(let failure):
            switch failure {
            case .connectionLost:
                "연결이 끊겨 행동을 받지 못했어요."
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

    /// 분할로 카드가 바뀔 때만 나뉘는 움직임을 보여준다. 모션 감소가 켜져 있으면 쓰지 않는다.
    private func startSplitMotion(from oldScreen: ProgressScreen, to newScreen: ProgressScreen) {
        guard !reduceMotion,
              case .currentAction(let oldCard, _) = oldScreen,
              case .currentAction(let newCard, _) = newScreen,
              newCard.origin?.id == oldCard.id
        else { return }
        splitGhost = SplitGhost(task: oldCard.task)
    }

    private func announceChange(from oldScreen: ProgressScreen, to newScreen: ProgressScreen) {
        var messages: [String] = []
        var oldCard: ActionCard?
        if case .currentAction(let card, _) = oldScreen { oldCard = card }
        if oldCard != nil, case .awaitingNextAction = newScreen {
            messages.append("행동을 완료했어요.")
        }
        switch newScreen {
        case .currentAction(let card, let smaller) where card.id == oldCard?.id:
            switch smaller {
            case .waiting: messages.append("더 쉬운 행동을 준비하고 있어요.")
            case .question(let question): messages.append(question)
            case .problem(let problem): messages.append(reason(for: problem))
            case nil: break
            }
        case .currentAction(let card, _):
            if let oldCard, card.origin?.id == oldCard.id {
                messages.append("더 쉬운 행동으로 나눴어요. ‘\(oldCard.task)’의 일부예요.")
            } else if oldCard?.origin?.id == card.id {
                messages.append("나누기 전 행동으로 되돌렸어요.")
            } else if case .onHold(let deferred, _) = oldScreen, deferred.contains(where: { $0.id == card.id }) {
                messages.append("보류한 행동을 재개했어요.")
            }
            messages.append("지금 할 행동: \(card.task)")
        case .awaitingFirstAction(_, let problem):
            messages.append(problem.map(reason(for:)) ?? "첫 행동을 준비하고 있어요.")
        case .awaitingNextAction(let problem):
            messages.append(problem.map(reason(for:)) ?? "다음 행동을 준비하고 있어요.")
        case .onHold(_, let status):
            if oldCard != nil { messages.append("행동을 보류했어요.") }
            switch status {
            case .waiting: messages.append("다른 행동을 준비하고 있어요.")
            case .problem(let problem): messages.append(reason(for: problem))
            case .noAction: messages.append("보류 중. 지금 할 수 있는 다른 행동이 없어요.")
            }
        case .goalInput:
            break
        }
        if !messages.isEmpty {
            AccessibilityNotification.Announcement(messages.joined(separator: " ")).post()
        }
    }
}

struct SplitGhost: Equatable {
    let id = UUID()
    let task: String
}

/// 분할 직전 카드의 위·아래 두 조각이 갈라지며 사라진다. 모션 감소가 켜져 있으면 쓰지 않는다.
private struct SplitGhostView: View {
    let ghost: SplitGhost
    let onFinish: @MainActor () -> Void
    @State private var apart = false

    var body: some View {
        GeometryReader { proxy in
            let height = proxy.size.height
            ZStack(alignment: .topLeading) {
                piece.mask(alignment: .top) { Rectangle().frame(height: height * 0.48) }
                    .offset(x: apart ? -6 : 0, y: apart ? -9 : 0)
                piece.mask(alignment: .bottom) { Rectangle().frame(height: height * 0.48) }
                    .offset(x: apart ? 12 : 0, y: apart ? 24 : 0)
            }
            .opacity(apart ? 0 : 0.85)
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .id(ghost.id)
        .task(id: ghost.id) {
            apart = false
            withAnimation(.timingCurve(0.2, 0.8, 0.2, 1, duration: Motion.split)) { apart = true }
            try? await Task.sleep(for: .seconds(Motion.split))
            onFinish()
        }
    }

    private var piece: some View {
        Text(ghost.task)
            .font(.title2.weight(.semibold))
            .padding(24)
            .padding(.top, 40)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 18))
            .overlay { RoundedRectangle(cornerRadius: 18).strokeBorder(Color(.separator), lineWidth: 1) }
    }
}

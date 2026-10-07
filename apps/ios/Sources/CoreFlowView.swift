import SwiftUI

enum Motion {
    static let nextCard: Double = 0.18
    /// 분할 전환 시간이다. 실제 휴대폰에서 이 값 하나로 조정한다.
    static let split: Double = 0.34
}

@MainActor
struct CoreFlowView: View {
    let flow: ProgressFlow

    @State private var goalInputDraft = GoalInput()
    @State private var goalContextExpanded = false
    @State private var criteriaText = ""
    @State private var showingGoal = false
    @State private var showingGoals = false
    @State private var editingGoal = false
    @State private var goalStatement = ""
    @State private var showingDeletion = false
    @State private var deletionGoal: GoalDetails?
    @State private var goalInputProblem: String?
    @State private var answerText = ""
    @State private var draftText = ""
    @State private var detailsExpanded = false
    @State private var storageFailed = false
    /// 분할 직전 행동의 할 일이다. 값이 있는 동안 나뉘는 움직임을 보여준다.
    @State private var splitGhost: SplitGhost?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private let accent = Color(red: 0.18, green: 0.27, blue: 0.16)

    private var trimmedGoal: String {
        goalInputDraft.statement.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var headerLayout: AnyLayout {
        dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
            : AnyLayout(HStackLayout(alignment: .top))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                headerLayout {
                    Text("Smallnext")
                        .font(.headline)
                        .accessibilityAddTraits(.isHeader)
                    if !dynamicTypeSize.isAccessibilitySize { Spacer() }
                    Button("목표 목록") { showingGoals = true }
                        .frame(minHeight: 44)
                    if flow.goalDetails != nil {
                        Button("목표 보기") {
                            editingGoal = false
                            goalStatement = flow.goalDetails?.statement ?? ""
                            showingGoal = true
                        }
                            .frame(minHeight: 44)
                    }
                }

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
                if let goalInputProblem {
                    Text(goalInputProblem).fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(24)
            .frame(maxWidth: 560, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .background(Color(.systemGroupedBackground))
        .tint(accent)
        .sheet(isPresented: $showingGoal) { goalView }
        .sheet(isPresented: $showingGoals) { goalsView }
        .onAppear {
            restoreDraft()
            goalInputDraft = flow.goalInput
            restoreSuggestionDraft()
        }
        .onChange(of: flow.goalDetails?.id) { _, _ in
            goalInputDraft = flow.goalInput
            restoreSuggestionDraft()
            goalContextExpanded = false
            splitGhost = nil
            restoreDraft()
        }
        .onChange(of: flow.screen) { oldScreen, newScreen in
            if case .currentAction(let oldCard, let oldSmaller) = oldScreen,
               case .currentAction(let newCard, let newSmaller) = newScreen,
               oldCard.id == newCard.id {
                // 초안 자동 저장은 같은 질문의 답과 펼친 설명을 지우거나 상태를 다시 알리지 않는다.
                if oldSmaller == newSmaller { return }
            } else {
                restoreDraft()
            }
            if newScreen == .goalInput { goalInputDraft = flow.goalInput }
            // 답 입력은 지금 보이는 질문에만 쓴다.
            restoreSuggestionDraft()
            startSplitMotion(from: oldScreen, to: newScreen)
            announceChange(from: oldScreen, to: newScreen)
        }
    }

    private var screenIdentity: String {
        switch flow.screen {
        case .goalInput: "goalInput"
        case .stoppedGoal: "stoppedGoal"
        case .preparingGoal: "preparingGoal"
        case .awaitingFirstAction(_, let problem): "awaitingFirstAction-\(String(describing: problem))"
        case .currentAction(let card, _): "currentAction-\(card.id)"
        case .awaitingNextAction(let problem): "awaitingNextAction-\(String(describing: problem))"
        case .onHold(_, let status): "onHold-\(String(describing: status))"
        }
    }

    @ViewBuilder
    private var screenContent: some View {
        switch flow.screen {
        case .stoppedGoal(let card):
            VStack(alignment: .leading, spacing: 16) {
                Text("목표 중단").font(.title2.bold()).accessibilityAddTraits(.isHeader)
                Text("진행 상태와 입력·기록을 보관했어요.")
                    .fixedSize(horizontal: false, vertical: true)
                if let card {
                    Text("마지막 행동").font(.headline)
                    Text(card.task).fixedSize(horizontal: false, vertical: true)
                    resultSection("이 행동에 남긴 결과", results: card.results)
                    if !card.draft.isEmpty {
                        Text("입력 초안").font(.headline)
                        Text(card.draft).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        case .preparingGoal(let question, let criteria, let problem):
            VStack(alignment: .leading, spacing: 16) {
                Text("목표 확인")
                    .font(.title2.bold()).accessibilityAddTraits(.isHeader)
                Text(flow.goalDetails?.statement ?? "").fixedSize(horizontal: false, vertical: true)
                if let question, problem == nil {
                    Text(question).font(.headline).fixedSize(horizontal: false, vertical: true)
                    TextField("알고 있는 답", text: suggestionBinding($answerText), axis: .vertical)
                        .textFieldStyle(.roundedBorder).accessibilityLabel("목표 확인 질문 답")
                    commandButton("답 보내기") { try flow.answerGoalQuestion(answerText) }
                        .disabled(answerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                } else if criteria != nil, problem == nil {
                    Text("완료 조건").font(.headline)
                    TextField("이 목표가 끝난 기준", text: suggestionBinding($criteriaText), axis: .vertical)
                        .textFieldStyle(.roundedBorder).accessibilityLabel("목표 완료 조건")
                    Text("현재 상태").font(.headline)
                    Text(flow.goalDetails?.context.currentState ?? "아직 알려주지 않았어요.")
                        .fixedSize(horizontal: false, vertical: true)
                    Text("완료 조건과 현재 상태를 확인해 주세요. 완료 조건은 직접 고칠 수 있어요.")
                        .fixedSize(horizontal: false, vertical: true)
                    commandButton("확인하고 시작") { try flow.confirmGoal(completionCriteria: criteriaText) }
                        .disabled(criteriaText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                } else {
                    suggestionStatus("목표를 정리하고 있어요.", problem: problem)
                }
            }
        case .goalInput:
            VStack(alignment: .leading, spacing: 16) {
                Text("목표를 한 문장으로 적어 주세요.")
                    .font(.title2.bold())
                    .accessibilityAddTraits(.isHeader)
                goalField("목표 한 문장", field: \.statement)
                DisclosureGroup("아는 맥락 보태기 (선택)", isExpanded: $goalContextExpanded) {
                    VStack(alignment: .leading, spacing: 16) {
                        goalField("기한 (선택)", field: \.deadline)
                        goalField("현재 상태 (선택)", field: \.currentState)
                        goalField("막힌 점 (선택)", field: \.blocker)
                        goalField("자료 링크 (선택, 한 줄에 하나)", field: \.materialLinks)
                        goalField("고른 발췌·요약 (선택)", field: \.materialExcerpt)
                        goalField("지금 쓸 수 있는 시간 (선택, 분)", field: \.availableMinutes)
                        Text("자료는 링크와 직접 고른 발췌·요약만 보내요. 링크의 내용은 자동으로 읽지 않아요.")
                            .font(.footnote).fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.top, 12)
                }
                commandButton("목표 정리") { try flow.prepareGoal() }
                .disabled(trimmedGoal.isEmpty)
            }
        case .awaitingFirstAction(_, let problem):
            VStack(alignment: .leading, spacing: 16) {
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

    private func goalField(_ title: String, field: WritableKeyPath<GoalInput, String>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.subheadline).fixedSize(horizontal: false, vertical: true)
            TextField(title, text: Binding(
                get: { goalInputDraft[keyPath: field] },
                set: { text in
                    guard flow.screen == .goalInput else { return }
                    goalInputDraft[keyPath: field] = text
                    goalInputProblem = nil
                    do {
                        try flow.updateGoalInput(goalInputDraft)
                        storageFailed = false
                    } catch {
                        storageFailed = true
                    }
                }
            ), axis: .vertical)
                .font(.body)
                .padding(12)
                .frame(minHeight: 44)
                .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12))
                .accessibilityLabel(title)
        }
    }

    private var goalsView: some View {
        NavigationStack {
            List {
                if flow.goals.isEmpty {
                    Text("저장한 목표가 없어요.")
                }
                ForEach(flow.goals) { goal in
                    Button {
                        if run({ try flow.selectGoal(goal.id) }) { showingGoals = false }
                    } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(goal.statement).font(.headline)
                                .fixedSize(horizontal: false, vertical: true)
                            Text(goal.isStopped ? "목표 중단" : "진행 중")
                                .font(.subheadline).foregroundStyle(.secondary)
                            Text("완료한 행동 \(goal.completedActionCount)개")
                                .font(.subheadline).foregroundStyle(.secondary)
                            if goal.id == flow.goalDetails?.id {
                                Label("선택한 목표", systemImage: "checkmark")
                                    .font(.subheadline)
                                    .foregroundStyle(accent)
                            }
                        }
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
                if storageFailed { Text("저장하지 못했어요. 다시 시도해 주세요.") }
            }
            .navigationTitle("목표 목록")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기") { showingGoals = false }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button("새 목표") {
                        if run({ try flow.startNewGoal() }) { showingGoals = false }
                    }
                }
            }
        }
    }

    private var goalView: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let goal = flow.goalDetails {
                        Text("목표").font(.headline).accessibilityAddTraits(.isHeader)
                        if editingGoal {
                            TextField("목표 문구", text: $goalStatement, axis: .vertical)
                                .textFieldStyle(.roundedBorder).accessibilityLabel("목표 문구")
                            Text("문구만 고쳐요. 완료 조건과 진행 상태는 유지해요.")
                                .fixedSize(horizontal: false, vertical: true)
                            commandButton("문구 저장", prominent: false) {
                                try flow.editGoalStatement(goalStatement)
                                editingGoal = false
                            }
                            .disabled(goalStatement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        } else {
                            Text(goal.statement).fixedSize(horizontal: false, vertical: true)
                            Button("문구 수정") { editingGoal = true }.frame(minHeight: 44)
                        }
                        Text("완료 조건").font(.headline).accessibilityAddTraits(.isHeader)
                        Text(goal.completionCriteria ?? "아직 확인하지 않았어요.")
                            .fixedSize(horizontal: false, vertical: true)
                        if !flow.goals.contains(where: { $0.id == goal.id && $0.isStopped }) {
                            Button("목표 중단") {
                                if run({ try flow.stopGoal() }) { showingGoal = false }
                            }
                            .frame(minHeight: 44)
                        }
                        Button("목표 삭제", role: .destructive) {
                            deletionGoal = goal
                            showingDeletion = true
                        }
                        .frame(minHeight: 44)
                    }
                    if storageFailed { Text("저장하지 못했어요. 다시 시도해 주세요.") }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .navigationTitle("목표 보기")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("닫기") { showingGoal = false }
                }
            }
            .alert("목표를 삭제할까요?", isPresented: $showingDeletion, presenting: deletionGoal) { goal in
                Button("삭제", role: .destructive) {
                    if run({ try flow.deleteGoal(goal.id, confirmed: true) }) {
                        showingGoal = false
                    }
                }
                Button("취소", role: .cancel) { }
            } message: { goal in
                Text("‘\(goal.statement)’의 행동·결과·입력·완료 기록을 지워요. 삭제 후에는 복구할 수 없어요.")
            }
        }
    }

    /// 대체 행동을 기다리거나 받지 못한 상태와 보류한 행동 목록을 보여준다. 각 행동은 '재개'할 수 있다.
    private func onHold(_ deferred: [ActionCard], status: HoldStatus) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(status == .noAction ? "보류 중" : "다음 행동 대기")
                .font(.title2.bold())
                .accessibilityAddTraits(.isHeader)
            switch status {
            case .waiting:
                suggestionStatus("다음 행동을 준비하고 있어요.", problem: nil)
            case .problem(let problem):
                suggestionStatus("다음 행동을 준비하고 있어요.", problem: problem)
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
                if let targetName = card.targetName {
                    Text("대상: \(targetName)")
                        .font(.headline)
                        .fixedSize(horizontal: false, vertical: true)
                }
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
                if card.targetDescription != nil || !card.materialLinks.isEmpty {
                    DisclosureGroup("설명과 자료", isExpanded: $detailsExpanded) {
                        VStack(alignment: .leading, spacing: 12) {
                            if let description = card.targetDescription {
                                Text(description)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            ForEach(card.materialLinks, id: \.self) { link in
                                Link(link.absoluteString, destination: link)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
                resultSection("앞서 남긴 결과", results: card.previousResults)
                resultSection("이 행동에 남긴 결과", results: card.results)
                VStack(alignment: .leading, spacing: 8) {
                    Text("행동 결과")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    TextField("문장이나 메모를 적어 주세요.", text: Binding(
                        get: { draftText },
                        set: { saveDraft($0, for: card.id) }
                    ), axis: .vertical)
                        .lineLimit(3...8)
                        .padding(12)
                        .background(Color(.tertiarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 10))
                        .accessibilityLabel("행동 결과 입력")
                    Text("작성 중인 내용은 자동 저장돼요.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    commandButton("결과 남기기", prominent: false) {
                        try flow.recordResult(draftText, for: card.id)
                        draftText = ""
                    }
                    .disabled(draftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    if storageFailed && draftText != card.draft {
                        commandButton("입력 다시 저장", prominent: false) { }
                    }
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                RoundedRectangle(cornerRadius: 18)
                    .fill(Color(.secondarySystemGroupedBackground))
                    .shadow(color: accent.opacity(0.10), radius: 0, x: 0, y: 5)
            }
            .overlay {
                RoundedRectangle(cornerRadius: 18)
                    .strokeBorder(Color(.separator), lineWidth: 1)
            }
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
                TextField("가장 먼저 막히는 지점", text: suggestionBinding($answerText), axis: .vertical)
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

    @ViewBuilder
    private func resultSection(_ title: String, results: [ActionResult]) -> some View {
        if !results.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(title)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                ForEach(results) { result in
                    Text(result.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func restoreSuggestionDraft() {
        answerText = flow.suggestionInput?.text ?? ""
        if case .preparingGoal(_, let criteria, _) = flow.screen {
            criteriaText = flow.suggestionInput?.text ?? criteria ?? ""
        } else { criteriaText = "" }
    }

    private func suggestionBinding(_ local: Binding<String>) -> Binding<String> {
        let requestID = flow.suggestionInput?.requestID
        return Binding(get: { local.wrappedValue }, set: { text in
            guard let requestID, flow.suggestionInput?.requestID == requestID else { return }
            local.wrappedValue = text
            do {
                try flow.updateSuggestionInput(text, for: requestID)
                storageFailed = false
            } catch { storageFailed = true }
        })
    }

    private func restoreDraft() {
        if case .currentAction(let card, _) = flow.screen { draftText = card.draft }
        else { draftText = "" }
        detailsExpanded = false
    }

    private func saveDraft(_ text: String, for actionID: Int64) {
        // 사라지는 카드의 늦은 입력이 새 카드의 입력란에 섞이지 않게 한다.
        guard case .currentAction(let card, _) = flow.screen, card.id == actionID else { return }
        draftText = text
        do {
            try flow.updateDraft(text, for: actionID)
            storageFailed = false
        } catch {
            if !storageFailed {
                AccessibilityNotification.Announcement("저장하지 못했어요. 다시 시도해 주세요.").post()
            }
            storageFailed = true
        }
    }

    @discardableResult
    private func run(_ command: @MainActor () throws -> Void) -> Bool {
        storageFailed = false
        goalInputProblem = nil
        do {
            if let input = flow.suggestionInput {
                let text: String
                let saved: String
                if case .preparingGoal(_, let criteria?, _) = flow.screen {
                    text = criteriaText
                    saved = input.text ?? criteria
                } else {
                    text = answerText
                    saved = input.text ?? ""
                }
                if text != saved { try flow.updateSuggestionInput(text, for: input.requestID) }
            }
            if flow.screen == .goalInput, goalInputDraft != flow.goalInput {
                try flow.updateGoalInput(goalInputDraft)
            }
            // 자동 저장에 실패한 입력이 있으면 화면을 떠나기 전에 다시 저장한다.
            if case .currentAction(let card, _) = flow.screen, card.draft != draftText {
                try flow.updateDraft(draftText, for: card.id)
            }
            try withAnimation(.easeInOut(duration: Motion.nextCard)) {
                try command()
            }
            return true
        } catch ProgressFlowError.invalidGoalContext {
            goalInputProblem = "자료 링크는 http:// 또는 https://로 입력해 주세요. 시간은 1 이상의 정수로 입력해 주세요."
        } catch {
            storageFailed = true
            AccessibilityNotification.Announcement(
                "저장하지 못했어요. 다시 시도해 주세요."
            ).post()
        }
        return false
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
        case .stoppedGoal:
            messages.append("목표를 중단했어요. 기록은 보관했어요.")
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
        case .onHold(let deferred, let status):
            if let oldCard {
                messages.append(deferred.contains(where: { $0.id == oldCard.id }) ? "행동을 보류했어요." : "행동을 완료했어요.")
            }
            switch status {
            case .waiting: messages.append("다음 행동을 준비하고 있어요.")
            case .problem(let problem): messages.append(reason(for: problem))
            case .noAction: messages.append("보류 중. 지금 할 수 있는 다른 행동이 없어요.")
            }
        case .preparingGoal(let question, let criteria, let problem):
            messages.append(problem.map(reason(for:)) ?? question ?? (criteria == nil ? "목표를 정리하고 있어요." : "완료 조건을 확인해 주세요."))
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

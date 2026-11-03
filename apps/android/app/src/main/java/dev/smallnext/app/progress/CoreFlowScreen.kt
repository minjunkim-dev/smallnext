package dev.smallnext.app.progress

import android.content.res.Resources
import android.util.Log
import androidx.annotation.StringRes
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.focusable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextFieldLabelPosition
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.collapse
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.expand
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import dev.smallnext.app.R
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 모션 값은 여기서만 조정한다. iOS `Motion`과 같은 값이다. 분할(0.34초)은 #353에서 더한다. */
object Motion {
    const val NEXT_CARD_MILLIS = 180
}

/** iOS 접근성 글꼴 크기(AX1 이상)에 대응하는 글꼴 배율이다. 이 배율부터 머리 영역을 쌓고 고정 버튼을 본문으로 옮긴다. */
internal const val LARGE_FONT_SCALE = 1.5f

/** iOS의 세로 compact 크기에 대응한다. 가로 화면에서는 고정 막대가 화면을 가린다. */
private const val COMPACT_HEIGHT = 480

@Composable
fun CoreFlowApp(flow: Deferred<ProgressFlow>) {
    val opened by produceState<Result<ProgressFlow>?>(null, flow) {
        value = try {
            Result.success(flow.await())
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            // 예외 메시지·스택에는 원문이 담길 수 있어 클래스 이름만 남긴다.
            Log.e("Smallnext", "Progress storage failed: ${error.javaClass.simpleName}")
            Result.failure(error)
        }
    }
    SmallnextTheme {
        Surface(Modifier.fillMaxSize()) {
            opened?.fold(
                onSuccess = { CoreFlowScreen(it) },
                onFailure = {
                    Text(
                        stringResource(R.string.storage_error),
                        Modifier.safeDrawingPadding().padding(32.dp),
                        style = MaterialTheme.typography.bodyLarge,
                    )
                },
            )
        }
    }
}

@Composable
internal fun SmallnextTheme(content: @Composable () -> Unit) {
    // iOS smallnextAccent와 같은 값이다. 채운 버튼 글자 대비를 4.5:1 이상으로 둔다(#61).
    val colors = if (isSystemInDarkTheme()) {
        darkColorScheme(primary = Color(0.55f, 0.78f, 0.50f), onPrimary = Color.Black)
    } else {
        lightColorScheme(primary = Color(0.18f, 0.27f, 0.16f), onPrimary = Color.White)
    }
    MaterialTheme(colorScheme = colors, content = content)
}

/** 진행 흐름의 상태만 그린다. 진행 규칙은 [ProgressFlow]에 있다. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun CoreFlowScreen(flow: ProgressFlow) {
    val state by flow.state.collectAsState()
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    var storageFailed by remember { mutableStateOf(false) }
    var showingGoal by rememberSaveable { mutableStateOf(false) }
    var announcement by remember { mutableStateOf("") }
    var shown by remember { mutableStateOf(state.screen) }
    val screen = state.screen
    // 같은 문장이 이어져도 다시 읽히도록 보이지 않는 문자로 값을 바꾼다.
    val announce = { message: String -> announcement = if (announcement == message) "$message\u200B" else message }
    LaunchedEffect(screen) {
        if (shown != screen) announcement(shown, screen, resources)?.let(announce)
        shown = screen
    }
    val focusManager = LocalFocusManager.current
    var goalInputProblem by remember { mutableStateOf<String?>(null) }
    /** 입력 자동 저장이다. 명령은 [run]으로 실행한다. */
    val save: (suspend () -> Unit) -> Unit = { command ->
        goalInputProblem = null
        scope.launch {
            try {
                // 화면을 다시 만들어도(회전 등) 시작한 저장과 명령은 끝까지 실행한다. 보이는 초안과 저장한 초안이 갈라지지 않게 한다.
                withContext(NonCancellable) { command() }
                storageFailed = false
            } catch (error: CancellationException) {
                throw error
            } catch (error: ProgressFlowException) {
                if (error.reason == ProgressFlowException.Reason.INVALID_GOAL_CONTEXT) {
                    goalInputProblem = resources.getString(R.string.goal_input_problem).also(announce)
                }
                // 그 밖에는 이미 바뀐 화면에 대한 늦은 입력이다(연타, 전환 중 사라지는 버튼). 저장은 앞 명령이 마쳤다.
            } catch (_: Exception) {
                // 자동 저장은 첫 실패만 알린다. 명령은 실패 표시를 지우고 시작하므로 매번 알린다.
                if (!storageFailed) announce(resources.getString(R.string.storage_failed))
                storageFailed = true
            }
        }
    }
    val run: (suspend () -> Unit) -> Unit = { command ->
        // 입력을 마친 화면을 떠나므로 키보드를 닫는다. 남은 키보드가 고정 버튼과 다음 화면을 가리지 않게 한다.
        focusManager.clearFocus()
        storageFailed = false
        save(command)
    }
    val density = LocalDensity.current
    val largeText = density.fontScale >= LARGE_FONT_SCALE
    val compactHeight = with(density) { LocalWindowInfo.current.containerSize.height.toDp() } < COMPACT_HEIGHT.dp
    val pinned = screen is ProgressScreen.CurrentAction && !largeText && !compactHeight

    Scaffold(
        bottomBar = {
            if (pinned) {
                Surface(tonalElevation = 3.dp, modifier = Modifier.testTag(PINNED_COMMANDS)) {
                    Column(Modifier.navigationBarsPadding().padding(horizontal = 24.dp, vertical = 12.dp), Arrangement.spacedBy(12.dp)) {
                        // 누른 버튼 가까이에 실패를 보여준다.
                        if (storageFailed) StorageFailure()
                        CommandButton(R.string.complete) { run { flow.complete(screen.card.id) } }
                    }
                }
            }
        },
    ) { padding ->
        // TalkBack 상태 안내다. 초점을 옮기지 않고 라이브 영역으로 읽힌다. 스크롤과 관계없이 화면 안에 둔다.
        Box(
            Modifier.padding(padding).size(1.dp).testTag(ANNOUNCEMENT).semantics {
                if (announcement.isNotEmpty()) {
                    liveRegion = LiveRegionMode.Polite
                    contentDescription = announcement
                }
            },
        )
        Column(
            Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding).imePadding()
                .verticalScroll(rememberScrollState()).padding(24.dp),
            Arrangement.spacedBy(24.dp),
        ) {
            Header(largeText, state.goal != null) { showingGoal = true }
            // 상태별 화면을 위쪽에 맞춰 교체한다. 이동 없이 투명도 전환만 쓴다.
            AnimatedContent(
                screen,
                contentAlignment = Alignment.TopStart,
                transitionSpec = { fadeIn(tween(Motion.NEXT_CARD_MILLIS)) togetherWith fadeOut(tween(Motion.NEXT_CARD_MILLIS)) },
                label = "screen",
                contentKey = { it.key },
            ) { target ->
                when (target) {
                    ProgressScreen.GoalInput -> GoalInputContent(state.goalInput, { input -> save { flow.updateGoalInput(input) } }) { input ->
                        // 누른 순간의 입력을 저장하고 검사하는 일을 한 명령으로 한다. 사이에 다른 입력이 끼어들지 않는다.
                        run { flow.prepareGoal(input) }
                    }
                    is ProgressScreen.PreparingGoal -> PreparingGoalContent(target, state.goal, state.suggestionInput, flow, run, save)
                    is ProgressScreen.AwaitingFirstAction ->
                        SuggestionStatus(R.string.preparing_first_action, target.problem, flow, run)
                    is ProgressScreen.CurrentAction -> ActionCardContent(target.card, commandsInBody = !pinned) { run { flow.complete(target.card.id) } }
                    is ProgressScreen.AwaitingNextAction -> Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        Heading(R.string.next_action_title, MaterialTheme.typography.titleLarge)
                        SuggestionStatus(R.string.preparing_next_action, target.problem, flow, run)
                    }
                }
            }
            if (storageFailed && !pinned) StorageFailure()
            goalInputProblem?.let { Text(it, style = MaterialTheme.typography.bodyLarge) }
        }
    }
    val goal = state.goal
    if (showingGoal && goal != null) {
        ModalBottomSheet(onDismissRequest = { showingGoal = false }) {
            Column(
                Modifier.verticalScroll(rememberScrollState()).padding(start = 24.dp, end = 24.dp, bottom = 24.dp),
                Arrangement.spacedBy(16.dp),
            ) {
                Heading(R.string.goal_heading, MaterialTheme.typography.titleMedium)
                Text(goal.statement)
                Heading(R.string.completion_criteria, MaterialTheme.typography.titleMedium)
                Text(goal.completionCriteria ?: stringResource(R.string.completion_criteria_missing))
            }
        }
    }
}

internal const val PINNED_COMMANDS = "pinnedCommands"
internal const val ANNOUNCEMENT = "announcement"

private val ProgressScreen.key: String
    get() = when (this) {
        ProgressScreen.GoalInput -> "goalInput"
        is ProgressScreen.PreparingGoal -> "preparingGoal"
        is ProgressScreen.AwaitingFirstAction -> "awaitingFirstAction-$problem"
        is ProgressScreen.CurrentAction -> "currentAction-${card.id}"
        is ProgressScreen.AwaitingNextAction -> "awaitingNextAction-$problem"
    }

/** 큰 글꼴에서는 머리 영역을 세로로 쌓는다. */
@Composable
private fun Header(largeText: Boolean, hasGoal: Boolean, onShowGoal: () -> Unit) {
    val title = @Composable { Heading(R.string.app_name, MaterialTheme.typography.titleMedium) }
    val goalButton = @Composable {
        if (hasGoal) TextButton(onShowGoal, Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.goal_view)) }
    }
    if (largeText) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            title()
            goalButton()
        }
    } else {
        Row(verticalAlignment = Alignment.CenterVertically) {
            title()
            Spacer(Modifier.weight(1f))
            goalButton()
        }
    }
}

private val GoalInputSaver = listSaver<GoalInput, String>(
    { listOf(it.statement, it.deadline, it.currentState, it.blocker, it.materialLinks, it.materialExcerpt, it.availableMinutes) },
    { GoalInput(it[0], it[1], it[2], it[3], it[4], it[5], it[6]) },
)

/** 입력은 바뀔 때마다 [save]로 초안에 저장한다. 선택 입력은 펼쳤을 때만 보인다. */
@Composable
private fun GoalInputContent(saved: GoalInput, save: (GoalInput) -> Unit, prepare: (GoalInput) -> Unit) {
    var input by rememberSaveable(stateSaver = GoalInputSaver) { mutableStateOf(saved) }
    // 다시 열었을 때 선택 입력에 내용이 있으면 펼친다. 보내질 내용과 입력 오류가 가려지지 않게 한다.
    var expanded by rememberSaveable {
        mutableStateOf(listOf(saved.deadline, saved.currentState, saved.blocker, saved.materialLinks, saved.materialExcerpt, saved.availableMinutes).any { it.isNotBlank() })
    }
    val edit = { changed: GoalInput ->
        input = changed
        save(changed)
    }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Heading(R.string.goal_input_title, MaterialTheme.typography.titleLarge)
        GoalField(R.string.goal_input_label, input.statement) { edit(input.copy(statement = it)) }
        TextButton(
            { expanded = !expanded },
            Modifier.fillMaxWidth().heightIn(min = 48.dp).semantics {
                if (expanded) collapse { expanded = false; true } else expand { expanded = true; true }
            },
        ) {
            Text(stringResource(R.string.goal_context_toggle), Modifier.weight(1f))
        }
        if (expanded) {
            GoalField(R.string.goal_deadline_label, input.deadline) { edit(input.copy(deadline = it)) }
            GoalField(R.string.goal_current_state_label, input.currentState) { edit(input.copy(currentState = it)) }
            GoalField(R.string.goal_blocker_label, input.blocker) { edit(input.copy(blocker = it)) }
            GoalField(R.string.goal_material_links_label, input.materialLinks) { edit(input.copy(materialLinks = it)) }
            GoalField(R.string.goal_material_excerpt_label, input.materialExcerpt) { edit(input.copy(materialExcerpt = it)) }
            GoalField(R.string.goal_available_minutes_label, input.availableMinutes) { edit(input.copy(availableMinutes = it)) }
            Text(stringResource(R.string.goal_material_notice), style = MaterialTheme.typography.bodySmall)
        }
        CommandButton(R.string.prepare_goal, enabled = input.statement.isNotBlank()) { prepare(input) }
    }
}

@Composable
private fun GoalField(@StringRes label: Int, value: String, onValueChange: (String) -> Unit) =
    LabeledField(stringResource(label), value, onValueChange)

/**
 * 레이블을 입력란 위에 둔다(iOS `goalField`). 떠 있는 레이블은 큰 글꼴에서 테두리와 겹친다.
 * 레이블 위치는 `TextFieldState` 입력란만 정할 수 있다. 레이블은 입력란의 이름으로 읽히고 입력한 글자는 그대로 읽힌다.
 */
@Composable
private fun LabeledField(label: String, value: String, onValueChange: (String) -> Unit, placeholder: String? = null) {
    val state = rememberTextFieldState(value)
    val current by rememberUpdatedState(value)
    val change by rememberUpdatedState(onValueChange)
    LaunchedEffect(state) { snapshotFlow { state.text.toString() }.collect { if (it != current) change(it) } }
    OutlinedTextField(
        state,
        Modifier.fillMaxWidth(),
        labelPosition = TextFieldLabelPosition.Above(),
        label = { Text(label) },
        placeholder = placeholder?.let { { Text(it) } },
    )
}

@Composable
private fun PreparingGoalContent(
    screen: ProgressScreen.PreparingGoal,
    goal: GoalDetails?,
    input: SuggestionInput?,
    flow: ProgressFlow,
    run: (suspend () -> Unit) -> Unit,
    save: (suspend () -> Unit) -> Unit,
) {
    // 이전 요청의 초안은 받지 않는다. 진행 흐름도 요청 ID로 늦은 입력을 거부한다.
    val autosave = { text: String -> input?.let { save { flow.updateSuggestionInput(text, it.requestId) } } }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Heading(R.string.goal_review_title, MaterialTheme.typography.titleLarge)
        Text(goal?.statement.orEmpty())
        val question = screen.question
        val criteria = screen.completionCriteria
        when {
            screen.problem == null && question != null -> {
                var answer by rememberSaveable(input?.requestId) { mutableStateOf(input?.text.orEmpty()) }
                // 새로 나타난 질문으로 입력 초점을 옮긴다. TalkBack 초점이 따라오는지는 실제 TalkBack으로 아직 확인하지 않았다. 초점을 받으면 질문이 보이도록 스크롤된다.
                val focus = remember { FocusRequester() }
                Text(question, Modifier.focusRequester(focus).focusable(), style = MaterialTheme.typography.titleMedium)
                LaunchedEffect(question) { focus.requestFocus() }
                key(input?.requestId) {
                    LabeledField(stringResource(R.string.goal_question_answer_label), answer, {
                        answer = it
                        autosave(it)
                    }, placeholder = stringResource(R.string.goal_question_prompt))
                }
                CommandButton(R.string.goal_question_send, enabled = answer.isNotBlank()) {
                    run { flow.run(Drafts(answer = answer)) { flow.answerGoalQuestion(answer) } }
                }
            }
            screen.problem == null && criteria != null -> {
                var edited by rememberSaveable(input?.requestId) { mutableStateOf(input?.text ?: criteria) }
                Text(stringResource(R.string.completion_criteria), style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    edited,
                    {
                        edited = it
                        autosave(it)
                    },
                    Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.completion_criteria_prompt)) },
                )
                Text(stringResource(R.string.current_state), style = MaterialTheme.typography.titleMedium)
                Text(goal?.context?.currentState ?: stringResource(R.string.current_state_missing))
                Text(stringResource(R.string.goal_review_guide))
                CommandButton(R.string.confirm_goal, enabled = edited.isNotBlank()) {
                    run { flow.run(Drafts(completionCriteria = edited)) { flow.confirmGoal(edited) } }
                }
            }
            else -> SuggestionStatus(R.string.preparing_goal, screen.problem, flow, run)
        }
    }
}

/** 카드는 할 일 → 완료 조건 → 예상 시간 순서로 보이고 읽힌다. */
@Composable
private fun ActionCardContent(card: ActionCard, commandsInBody: Boolean, complete: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(24.dp)) {
        Heading(R.string.current_action_title, MaterialTheme.typography.titleLarge)
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(24.dp), Arrangement.spacedBy(16.dp)) {
                Text(
                    card.task,
                    Modifier.semantics { heading() },
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                )
                HorizontalDivider()
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        stringResource(R.string.completion_criteria),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(card.doneWhen, style = MaterialTheme.typography.bodyLarge)
                }
                Text(
                    stringResource(R.string.estimated_minutes, card.estimatedMinutes),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (commandsInBody) CommandButton(R.string.complete, onClick = complete)
    }
}

/** 기다리는 중이면 진행 표시와 '취소'를, 문제가 있으면 짧은 이유와 '다시 시도'를 보여준다. */
@Composable
private fun SuggestionStatus(@StringRes waiting: Int, problem: SuggestionProblem?, flow: ProgressFlow, run: (suspend () -> Unit) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        if (problem != null) {
            Text(stringResource(problem.reason), style = MaterialTheme.typography.bodyLarge)
            CommandButton(R.string.retry) { run(flow::retrySuggestion) }
        } else {
            val message = stringResource(waiting)
            // iOS처럼 진행 표시에도 대기 문장을 이름으로 붙인다.
            CircularProgressIndicator(Modifier.semantics { contentDescription = message })
            Text(message, style = MaterialTheme.typography.bodyLarge)
            CommandButton(R.string.cancel, prominent = false) { run(flow::cancelSuggestion) }
        }
    }
}

@Composable
private fun Heading(@StringRes text: Int, style: androidx.compose.ui.text.TextStyle) {
    Text(stringResource(text), Modifier.semantics { heading() }, style = style)
}

@Composable
private fun StorageFailure() {
    Text(stringResource(R.string.storage_failed), style = MaterialTheme.typography.bodyLarge)
}

@Composable
private fun CommandButton(@StringRes title: Int, enabled: Boolean = true, prominent: Boolean = true, onClick: () -> Unit) {
    val modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)
    if (prominent) {
        Button(onClick, modifier, enabled) { Text(stringResource(title)) }
    } else {
        OutlinedButton(onClick, modifier, enabled) { Text(stringResource(title)) }
    }
}

@get:StringRes
internal val SuggestionProblem.reason: Int
    get() = when (this) {
        SuggestionProblem.Unsuitable -> R.string.problem_unsuitable
        SuggestionProblem.Interrupted -> R.string.problem_interrupted
        SuggestionProblem.Cancelled -> R.string.problem_cancelled
        is SuggestionProblem.Failure -> when (failure) {
            SuggestionFailure.CONNECTION_LOST -> R.string.failure_connection_lost
            SuggestionFailure.REJECTED -> R.string.failure_rejected
            SuggestionFailure.UNDECIDABLE -> R.string.failure_undecidable
            SuggestionFailure.FAILED -> R.string.failure_failed
            SuggestionFailure.TIMED_OUT -> R.string.failure_timed_out
            SuggestionFailure.BUDGET_LIMIT -> R.string.failure_budget_limit
            SuggestionFailure.UNAVAILABLE -> R.string.failure_unavailable
        }
    }

/** iOS `announceChange`와 같은 조건과 문장이다. 이 단계에서 닿는 화면만 다룬다. */
private fun announcement(old: ProgressScreen, new: ProgressScreen, resources: Resources): String? {
    val messages = buildList {
        if (old is ProgressScreen.CurrentAction && new is ProgressScreen.AwaitingNextAction) add(resources.getString(R.string.announce_completed))
        when (new) {
            is ProgressScreen.CurrentAction -> if ((old as? ProgressScreen.CurrentAction)?.card?.id != new.card.id) {
                add(resources.getString(R.string.announce_current_action, new.card.task))
            }
            is ProgressScreen.AwaitingFirstAction -> add(resources.getString(new.problem?.reason ?: R.string.preparing_first_action))
            is ProgressScreen.AwaitingNextAction -> add(resources.getString(new.problem?.reason ?: R.string.preparing_next_action))
            // 질문은 초점을 옮겨 읽힌다. iOS는 초점을 옮기지 않고 질문을 안내한다.
            is ProgressScreen.PreparingGoal -> if (new.problem != null || new.question == null) add(
                resources.getString(
                    new.problem?.reason ?: if (new.completionCriteria == null) R.string.preparing_goal else R.string.check_completion_criteria,
                ),
            )
            ProgressScreen.GoalInput -> Unit
        }
    }
    return messages.joinToString(" ").ifEmpty { null }
}

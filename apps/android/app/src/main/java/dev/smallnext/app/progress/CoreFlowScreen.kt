package dev.smallnext.app.progress

import android.content.res.Resources
import android.util.Log
import androidx.annotation.StringRes
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import dev.smallnext.app.R
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

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
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
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
    val run: (suspend () -> Unit) -> Unit = { command ->
        // 입력을 마친 화면을 떠나므로 키보드를 닫는다. 남은 키보드가 고정 버튼과 다음 화면을 가리지 않게 한다.
        focusManager.clearFocus()
        scope.launch {
            storageFailed = false
            try {
                command()
            } catch (error: CancellationException) {
                throw error
            } catch (_: ProgressFlowException) {
                // 이미 바뀐 화면에 대한 늦은 입력이다(연타, 전환 중 사라지는 버튼). 저장은 앞 명령이 마쳤다.
            } catch (_: Exception) {
                storageFailed = true
                announce(resources.getString(R.string.storage_failed))
            }
        }
    }
    // 입력 초안 자동 저장이다. 키보드를 닫지 않는다. 실패는 첫 번째만 알려 입력마다 같은 안내가 반복되지 않게 한다.
    val saveDraft = { text: String, actionId: Long ->
        scope.launch {
            try {
                flow.updateDraft(text, actionId)
                storageFailed = false
            } catch (error: CancellationException) {
                throw error
            } catch (_: ProgressFlowException) {
                // 사라지는 카드에 늦게 들어온 입력이다. 다른 카드에 저장하지 않는다.
            } catch (_: Exception) {
                if (!storageFailed) announce(resources.getString(R.string.storage_failed))
                storageFailed = true
            }
        }
    }
    var resultFocused by remember { mutableStateOf(false) }
    val density = LocalDensity.current
    val largeText = density.fontScale >= LARGE_FONT_SCALE
    val compactHeight = with(density) { LocalWindowInfo.current.containerSize.height.toDp() } < COMPACT_HEIGHT.dp
    // 결과를 적는 동안은 키보드 위 공간이 좁아 고정 막대가 입력란을 가린다. 그래서 본문으로 옮긴다.
    val writingResult = resultFocused && WindowInsets.isImeVisible
    val pinned = screen is ProgressScreen.CurrentAction && !largeText && !compactHeight && !writingResult

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
                    ProgressScreen.GoalInput -> GoalInputContent(state.goalInput) { input -> run { flow.prepareGoal(input) } }
                    is ProgressScreen.PreparingGoal -> PreparingGoalContent(target, state.goal, flow, run)
                    is ProgressScreen.AwaitingFirstAction ->
                        SuggestionStatus(R.string.preparing_first_action, target.problem, flow, run)
                    is ProgressScreen.CurrentAction -> ActionCardContent(
                        target.card,
                        commandsInBody = !pinned,
                        storageFailed = storageFailed,
                        flow = flow,
                        run = run,
                        saveDraft = saveDraft,
                        onResultFocus = { resultFocused = it },
                    ) { run { flow.complete(target.card.id) } }
                    is ProgressScreen.AwaitingNextAction -> Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        Heading(R.string.next_action_title, MaterialTheme.typography.titleLarge)
                        SuggestionStatus(R.string.preparing_next_action, target.problem, flow, run)
                    }
                }
            }
            if (storageFailed && !pinned) StorageFailure()
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

@Composable
private fun GoalInputContent(saved: GoalInput, prepare: (GoalInput) -> Unit) {
    var statement by rememberSaveable { mutableStateOf(saved.statement) }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Heading(R.string.goal_input_title, MaterialTheme.typography.titleLarge)
        OutlinedTextField(
            statement,
            { statement = it },
            Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.goal_input_label)) },
        )
        CommandButton(R.string.prepare_goal, enabled = statement.isNotBlank()) { prepare(saved.copy(statement = statement)) }
    }
}

@Composable
private fun PreparingGoalContent(
    screen: ProgressScreen.PreparingGoal,
    goal: GoalDetails?,
    flow: ProgressFlow,
    run: (suspend () -> Unit) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Heading(R.string.goal_review_title, MaterialTheme.typography.titleLarge)
        Text(goal?.statement.orEmpty())
        val question = screen.question
        val criteria = screen.completionCriteria
        when {
            screen.problem == null && question != null -> {
                var answer by rememberSaveable(question) { mutableStateOf("") }
                Text(question, style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    answer,
                    { answer = it },
                    Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.goal_question_prompt)) },
                )
                CommandButton(R.string.goal_question_send, enabled = answer.isNotBlank()) { run { flow.answerGoalQuestion(answer) } }
            }
            screen.problem == null && criteria != null -> {
                var edited by rememberSaveable(criteria) { mutableStateOf(criteria) }
                Text(stringResource(R.string.completion_criteria), style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    edited,
                    { edited = it },
                    Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.completion_criteria_prompt)) },
                )
                Text(stringResource(R.string.current_state), style = MaterialTheme.typography.titleMedium)
                Text(goal?.context?.currentState ?: stringResource(R.string.current_state_missing))
                Text(stringResource(R.string.goal_review_guide))
                CommandButton(R.string.confirm_goal, enabled = edited.isNotBlank()) { run { flow.confirmGoal(edited) } }
            }
            else -> SuggestionStatus(R.string.preparing_goal, screen.problem, flow, run)
        }
    }
}

/**
 * 카드는 할 일 → 완료 조건 → 예상 시간 순서로 보이고 읽힌다. 그 아래에 설명과 자료, 결과, 결과 입력이 온다.
 * 입력 초안은 카드마다 따로 둔다. 사라지는 카드의 입력이 새 카드의 입력란에 섞이지 않는다.
 */
@Composable
private fun ActionCardContent(
    card: ActionCard,
    commandsInBody: Boolean,
    storageFailed: Boolean,
    flow: ProgressFlow,
    run: (suspend () -> Unit) -> Unit,
    saveDraft: (String, Long) -> Job,
    onResultFocus: (Boolean) -> Unit,
    complete: () -> Unit,
) {
    var draftText by rememberSaveable(card.id) { mutableStateOf(card.draft) }
    var detailsExpanded by rememberSaveable(card.id) { mutableStateOf(false) }
    // 기록하는 동안 버튼을 꺼 연타로 같은 결과가 두 번 기록되지 않게 한다.
    var recording by remember(card.id) { mutableStateOf(false) }
    // 마지막 자동 저장이다. 결과를 기록하기 전에 끝나기를 기다려, 늦은 초안 저장이 기록한 결과를 초안으로 되살리지 않게 한다.
    val lastSave = remember(card.id) { arrayOfNulls<Job>(1) }
    val uriHandler = LocalUriHandler.current
    Column(verticalArrangement = Arrangement.spacedBy(24.dp)) {
        Heading(R.string.current_action_title, MaterialTheme.typography.titleLarge)
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(24.dp), Arrangement.spacedBy(16.dp)) {
                card.targetName?.let { Text(stringResource(R.string.target_name, it), style = MaterialTheme.typography.titleMedium) }
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
                if (card.targetDescription != null || card.materialLinks.isNotEmpty()) {
                    val expansion = stringResource(if (detailsExpanded) R.string.expanded else R.string.collapsed)
                    TextButton(
                        { detailsExpanded = !detailsExpanded },
                        Modifier.heightIn(min = 48.dp).semantics { stateDescription = expansion },
                    ) { Text(stringResource(R.string.details_and_materials)) }
                    if (detailsExpanded) {
                        card.targetDescription?.let { Text(it, style = MaterialTheme.typography.bodyLarge) }
                        // 기기 브라우저로 연다. 열 앱이 없어도 화면을 닫지 않는다.
                        for (link in card.materialLinks.filter(CandidatePolicy::isWebLink)) {
                            TextButton({ runCatching { uriHandler.openUri(link) } }, Modifier.heightIn(min = 48.dp)) { Text(link) }
                        }
                    }
                }
                ResultSection(R.string.previous_results, card.previousResults)
                ResultSection(R.string.action_results, card.results)
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        draftText,
                        { text ->
                            // 사라지는 카드에 늦게 들어온 입력은 받지 않는다.
                            if ((flow.state.value.screen as? ProgressScreen.CurrentAction)?.card?.id == card.id) {
                                draftText = text
                                lastSave[0] = saveDraft(text, card.id)
                            }
                        },
                        Modifier.fillMaxWidth().onFocusChanged { onResultFocus(it.isFocused) },
                        // 편집란의 contentDescription은 TalkBack이 입력한 글 대신 읽을 수 있어 레이블로 둔다.
                        label = { Text(stringResource(R.string.action_result_input)) },
                        placeholder = { Text(stringResource(R.string.action_result_placeholder)) },
                        minLines = 3,
                        maxLines = 8,
                    )
                    Text(
                        stringResource(R.string.draft_autosaved),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    SecondaryButton(R.string.record_result, enabled = draftText.isNotBlank() && !recording) {
                        // 다시 그리기 전에 들어온 두 번째 탭도 막는다.
                        if (recording) return@SecondaryButton
                        val text = draftText
                        recording = true
                        run {
                            try {
                                lastSave[0]?.join()
                                flow.recordResult(text, card.id)
                                // 기록하는 동안 더 적은 내용은 초안으로 남긴다.
                                if (draftText == text) draftText = ""
                            } finally {
                                recording = false
                            }
                        }
                    }
                    if (storageFailed && draftText != card.draft) SecondaryButton(R.string.save_draft_again) { lastSave[0] = saveDraft(draftText, card.id) }
                }
            }
        }
        if (commandsInBody) CommandButton(R.string.complete, onClick = complete)
    }
}

@Composable
private fun ResultSection(@StringRes title: Int, results: List<ActionResult>) {
    if (results.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(stringResource(title), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        results.forEach { Text(it.body, style = MaterialTheme.typography.bodyLarge) }
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

@Composable
private fun SecondaryButton(@StringRes title: Int, enabled: Boolean = true, onClick: () -> Unit) {
    OutlinedButton(onClick, Modifier.fillMaxWidth().heightIn(min = 48.dp), enabled) { Text(stringResource(title)) }
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
            is ProgressScreen.PreparingGoal -> add(
                new.problem?.let { resources.getString(it.reason) } ?: new.question
                    ?: resources.getString(if (new.completionCriteria == null) R.string.preparing_goal else R.string.check_completion_criteria),
            )
            ProgressScreen.GoalInput -> Unit
        }
    }
    return messages.joinToString(" ").ifEmpty { null }
}

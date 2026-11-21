package dev.smallnext.app.progress

import android.animation.ValueAnimator
import android.content.res.Resources
import android.util.Log
import androidx.annotation.StringRes
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.focusable
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
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
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.runtime.withFrameNanos
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
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
import androidx.compose.ui.semantics.collapse
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.expand
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.hideFromAccessibility
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import dev.smallnext.app.R
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** 모션 값은 여기서만 조정한다. iOS `Motion`·`SplitGhostView`와 같은 값이다. */
object Motion {
    const val NEXT_CARD_MILLIS = 180
    /** 분할 직전 카드의 위·아래 조각이 갈라지며 사라지는 시간과 곡선, 조각마다 끝 위치다. */
    const val SPLIT_MILLIS = 340
    val SPLIT_EASING = CubicBezierEasing(0.2f, 0.8f, 0.2f, 1f)
    val SPLIT_TOP = DpOffset((-6).dp, (-9).dp)
    val SPLIT_BOTTOM = DpOffset(12.dp, 24.dp)
}

/**
 * 애니메이터 배율이 0이면(개발자 옵션·'애니메이션 삭제') 분할 장식을 그리지 않는다.
 * 스크롤과 전환은 Compose가 같은 배율(MotionDurationScale)로 줄여 배율 0이면 바로 끝난다.
 */
internal fun animationsRemoved() = !ValueAnimator.areAnimatorsEnabled()

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
internal fun CoreFlowScreen(flow: ProgressFlow, reduceMotion: Boolean = remember { animationsRemoved() }) {
    val state by flow.state.collectAsState()
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    var storageFailed by remember { mutableStateOf(false) }
    var showingGoal by rememberSaveable { mutableStateOf(false) }
    var announcement by remember { mutableStateOf("") }
    var shown by remember { mutableStateOf(state.screen) }
    val screen = state.screen
    var splitGhost by remember { mutableStateOf<SplitGhost?>(null) }
    // 되돌린 원래 행동이다. 이 행동이 현재 행동인 동안 작은 행동이 보류로 간 것을 알린다.
    var undoneActionId by remember { mutableStateOf<Long?>(null) }
    // 같은 문장이 이어져도 다시 읽히도록 보이지 않는 문자로 값을 바꾼다.
    val announce = { message: String -> announcement = if (announcement == message) "$message\u200B" else message }
    LaunchedEffect(screen) {
        if (shown != screen) {
            announcement(shown, screen, resources)?.let(announce)
            val old = (shown as? ProgressScreen.CurrentAction)?.card
            val new = (screen as? ProgressScreen.CurrentAction)?.card
            if (old != null && new != null && old.id != new.id) {
                if (new.origin?.id == old.id && !reduceMotion) splitGhost = SplitGhost(old.task)
                if (old.origin?.id == new.id) undoneActionId = new.id
            }
            if (new?.id != undoneActionId) undoneActionId = null
        }
        shown = screen
    }
    val focusManager = LocalFocusManager.current
    var goalInputProblem by remember { mutableStateOf<String?>(null) }
    /** 입력 자동 저장이다. 명령은 [run]으로 실행한다. */
    val save: (suspend () -> Unit) -> Unit = { command ->
        goalInputProblem = null
        // 디스패치를 기다리지 않고 바로 시작한다. 시작 전에 화면이 다시 만들어져 저장이 취소되지 않게 한다.
        scope.launch(start = CoroutineStart.UNDISPATCHED) {
            try {
                // 화면을 다시 만들어도(회전 등) 시작한 저장과 명령은 끝까지 실행한다. 보이는 초안과 저장한 초안이 갈라지지 않게 한다.
                withContext(NonCancellable) { command() }
                storageFailed = false
            } catch (error: CancellationException) {
                throw error
            } catch (error: ProgressFlowException) {
                when (error.reason) {
                    ProgressFlowException.Reason.INVALID_GOAL_CONTEXT ->
                        goalInputProblem = resources.getString(R.string.goal_input_problem).also(announce)
                    // 답 초안은 명령 전에 저장했다. 답 저장만 되돌렸다.
                    ProgressFlowException.Reason.ANSWER_EXCEEDS_REQUEST_LIMIT ->
                        goalInputProblem = resources.getString(R.string.answer_too_long).also(announce)
                    else -> Unit
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
    // 카드별로 마지막에 입력한 초안이다. 저장하지 못했으면 완료 전에 다시 저장한다.
    val draftInputs = remember { mutableMapOf<Long, String>() }
    // 입력 초안 자동 저장이다. 키보드를 닫지 않는다. 실패는 첫 번째만 알려 입력마다 같은 안내가 반복되지 않게 한다.
    val saveDraft = { text: String, actionId: Long ->
        draftInputs[actionId] = text
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
    // '결과 남기기'는 마지막 자동 저장을 기다린다. 그동안 누른 '완료'가 앞질러 결과를 거부하게 하지 않도록 누른 순서대로 실행한다.
    val cardCommands = remember { Mutex() }
    // iOS `run(saving:)`와 같다. 카드를 바꾸는 명령 전에 저장하지 못한 입력을 먼저 저장하고, 실패하면 명령을 실행하지 않는다.
    // 카드가 바뀐 뒤 도착한 초안 저장은 거부되므로 '완료'·'더 작게'·'되돌리기' 모두 이 경로를 쓴다.
    val cardCommand = { actionId: Long, command: suspend () -> Unit ->
        run {
            cardCommands.withLock {
                val saved = (flow.state.value.screen as? ProgressScreen.CurrentAction)?.card?.takeIf { it.id == actionId }?.draft
                val input = draftInputs[actionId]
                if (saved != null && input != null && input != saved) flow.updateDraft(input, actionId)
                command()
            }
        }
    }
    val completeCard = { actionId: Long -> cardCommand(actionId) { flow.complete(actionId) } }
    val density = LocalDensity.current
    val largeText = density.fontScale >= LARGE_FONT_SCALE
    val compactHeight = with(density) { LocalWindowInfo.current.containerSize.height.toDp() } < COMPACT_HEIGHT.dp
    // 결과를 적는 동안은 키보드 위 공간이 좁아 고정 막대가 입력란을 가린다. 그래서 본문으로 옮긴다.
    val writingResult = resultFocused && WindowInsets.isImeVisible
    // 답 입력은 높아서 본문에 둔다. 질문이 나타나면 고정을 풀고 질문으로 스크롤한다.
    val asking = (screen as? ProgressScreen.CurrentAction)?.smaller is SmallerStatus.Question
    val pinned = screen is ProgressScreen.CurrentAction && !largeText && !compactHeight && !writingResult && !asking
    val scroll = rememberScrollState()
    val currentCardId = (screen as? ProgressScreen.CurrentAction)?.card?.id
    val smaller = { currentCardId?.let { cardCommand(it, flow::makeSmaller) } ?: Unit }
    val undo = { actionId: Long -> cardCommand(actionId, flow::undoSplit) }
    val cancel = { run(flow::cancelSuggestion) }
    Scaffold(
        bottomBar = {
            if (pinned) {
                Surface(tonalElevation = 3.dp, modifier = Modifier.testTag(PINNED_COMMANDS)) {
                    Column(Modifier.navigationBarsPadding().padding(horizontal = 24.dp, vertical = 12.dp), Arrangement.spacedBy(12.dp)) {
                        // 누른 버튼 가까이에 실패를 보여준다.
                        if (storageFailed) StorageFailure()
                        // '완료'를 더 작게 상태 위에 둔다(#64).
                        CommandButton(R.string.complete) { completeCard(screen.card.id) }
                        // 대기 상태의 높이를 미리 잡아 '더 작게'를 눌러도 '완료'가 움직이지 않고 '취소'가 같은 자리에 오지 않게 한다(#64).
                        ReservingHeight({ SmallerSection(SmallerStatus.Waiting, {}, {}, enabled = false) }) { SmallerSection(screen.smaller, smaller, cancel) }
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
                .verticalScroll(scroll).padding(24.dp),
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
                    is ProgressScreen.CurrentAction -> ActionCardContent(
                        target.card,
                        smallerStatus = target.smaller,
                        commandsInBody = !pinned,
                        splitGhost = splitGhost,
                        onSplitFinished = { splitGhost = null },
                        undone = undoneActionId == target.card.id,
                        suggestionInput = state.suggestionInput,
                        smaller = smaller,
                        cancel = cancel,
                        undo = { undo(target.card.id) },
                        save = save,
                        storageFailed = storageFailed,
                        flow = flow,
                        run = run,
                        saveDraft = saveDraft,
                        onResultFocus = { resultFocused = it },
                        cardCommands = cardCommands,
                        draftInputs = draftInputs,
                    ) { completeCard(target.card.id) }
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
internal const val SPLIT_GHOST = "splitGhost"

/**
 * [reserve]와 [content] 중 큰 높이를 차지한다. [reserve]는 투명하고 의미 트리에서 지워 보이지도 읽히지도 않는다.
 * [reserve]의 버튼은 꺼서 초점과 입력을 받지 않게 한다. iOS는 숨긴 뷰를 겹쳐 같은 효과를 얻는다(`hidden()`).
 */
@Composable
private fun ReservingHeight(reserve: @Composable () -> Unit, content: @Composable () -> Unit) {
    Box {
        Box(Modifier.alpha(0f).clearAndSetSemantics {}) { reserve() }
        content()
    }
}

/**
 * 더 작게 상태다. 기다리면 진행 표시와 '취소'를, 문제가 있으면 짧은 이유와 다시 시도인 '더 작게'를 보여준다.
 * 질문은 [QuestionAnswer]가 그린다.
 */
@Composable
private fun SmallerSection(status: SmallerStatus?, smaller: () -> Unit, cancel: () -> Unit, enabled: Boolean = true) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        when (status) {
            null -> CommandButton(R.string.smaller, enabled, prominent = false, onClick = smaller)
            SmallerStatus.Waiting -> {
                val message = stringResource(R.string.preparing_smaller)
                Row(Modifier.semantics(mergeDescendants = true) {}, Arrangement.spacedBy(12.dp), Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(24.dp))
                    Text(message, style = MaterialTheme.typography.bodyLarge)
                }
                CommandButton(R.string.cancel, enabled, prominent = false, onClick = cancel)
            }
            is SmallerStatus.Question -> Unit
            is SmallerStatus.Problem -> {
                Text(stringResource(status.problem.reason), style = MaterialTheme.typography.bodyLarge)
                CommandButton(R.string.smaller, enabled, prominent = false, onClick = smaller)
            }
        }
    }
}

/** 분할 직전 카드다. 같은 할 일이어도 새로 만든 값마다 다시 움직인다(값 동등성을 쓰지 않는다). */
internal class SplitGhost(val task: String)

/** 분할 직전 카드의 위·아래 두 조각이 갈라지며 사라진다. 접근성 트리에서는 숨긴다. */
@Composable
private fun BoxScope.SplitGhostView(ghost: SplitGhost, onFinish: () -> Unit) {
    val progress = remember(ghost) { Animatable(0f) }
    val finish by rememberUpdatedState(onFinish)
    LaunchedEffect(ghost) {
        progress.animateTo(1f, tween(Motion.SPLIT_MILLIS, easing = Motion.SPLIT_EASING))
        finish()
    }
    val density = LocalDensity.current
    Box(Modifier.matchParentSize().testTag(SPLIT_GHOST).semantics { hideFromAccessibility() }.graphicsLayer { alpha = 0.85f * (1 - progress.value) }) {
        for ((offset, top) in listOf(Motion.SPLIT_TOP to true, Motion.SPLIT_BOTTOM to false)) {
            Card(
                Modifier.matchParentSize().graphicsLayer {
                    translationX = with(density) { offset.x.toPx() } * progress.value
                    translationY = with(density) { offset.y.toPx() } * progress.value
                }.drawWithContent {
                    val edge = size.height * 0.48f
                    if (top) clipRect(bottom = edge) { this@drawWithContent.drawContent() }
                    else clipRect(top = size.height - edge) { this@drawWithContent.drawContent() }
                },
            ) {
                Text(ghost.task, Modifier.padding(24.dp), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

/** 더 작게의 확인 질문 하나다. 나타나면 초점을 질문으로 옮긴다. 답은 막힘 원인으로 저장된다. */
@Composable
private fun QuestionAnswer(
    question: String,
    input: SuggestionInput?,
    flow: ProgressFlow,
    run: (suspend () -> Unit) -> Unit,
    save: (suspend () -> Unit) -> Unit,
) {
    val focus = remember { FocusRequester() }
    val visible = remember { BringIntoViewRequester() }
    Column(Modifier.bringIntoViewRequester(visible), Arrangement.spacedBy(12.dp)) {
        Text(
            question,
            Modifier.focusRequester(focus).focusable().semantics { heading() },
            style = MaterialTheme.typography.titleMedium,
        )
        LaunchedEffect(question) {
            // 고정 막대가 본문으로 옮겨져 배치된 다음에 스크롤한다. 질문과 답 입력란이 함께 보이게 한다.
            // 스크롤은 Compose의 애니메이터 배율(MotionDurationScale)을 따라 배율 0이면 바로 끝난다.
            withFrameNanos {}
            visible.bringIntoView()
            focus.requestFocus()
        }
        key(input?.requestId) {
            val answer = rememberTextFieldState(input?.text.orEmpty())
            // 이전 요청의 초안은 받지 않는다. 진행 흐름도 요청 ID로 늦은 입력을 거부한다.
            AutosaveChanges(input?.text.orEmpty(), { answer.text.toString() }) { text ->
                input?.let { save { flow.updateSuggestionInput(text, it.requestId) } }
            }
            LabeledField(stringResource(R.string.smaller_question_prompt), answer)
            CommandButton(R.string.answer, enabled = answer.text.isNotBlank()) {
                val text = answer.text.toString()
                run { flow.run(Drafts(answer = text)) { flow.answerQuestion(text) } }
            }
        }
    }
}

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

/** 입력은 바뀔 때마다 [save]로 초안에 저장한다. 선택 입력은 펼쳤을 때만 보인다. */
@Composable
private fun GoalInputContent(saved: GoalInput, save: (GoalInput) -> Unit, prepare: (GoalInput) -> Unit) {
    // 보이는 글자가 기준이다. 제출과 자동 저장 모두 입력란 상태를 바로 읽는다.
    val statement = rememberTextFieldState(saved.statement)
    val deadline = rememberTextFieldState(saved.deadline)
    val currentState = rememberTextFieldState(saved.currentState)
    val blocker = rememberTextFieldState(saved.blocker)
    val materialLinks = rememberTextFieldState(saved.materialLinks)
    val materialExcerpt = rememberTextFieldState(saved.materialExcerpt)
    val availableMinutes = rememberTextFieldState(saved.availableMinutes)
    val read = {
        GoalInput(
            statement.text.toString(),
            deadline.text.toString(),
            currentState.text.toString(),
            blocker.text.toString(),
            materialLinks.text.toString(),
            materialExcerpt.text.toString(),
            availableMinutes.text.toString(),
        )
    }
    AutosaveChanges(saved, read, save)
    // 다시 열었을 때 선택 입력에 내용이 있으면 펼친다. 보내질 내용과 입력 오류가 가려지지 않게 한다.
    var expanded by rememberSaveable {
        mutableStateOf(listOf(saved.deadline, saved.currentState, saved.blocker, saved.materialLinks, saved.materialExcerpt, saved.availableMinutes).any { it.isNotBlank() })
    }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Heading(R.string.goal_input_title, MaterialTheme.typography.titleLarge)
        GoalField(R.string.goal_input_label, statement)
        TextButton(
            { expanded = !expanded },
            Modifier.fillMaxWidth().heightIn(min = 48.dp).semantics {
                if (expanded) collapse { expanded = false; true } else expand { expanded = true; true }
            },
        ) {
            Text(stringResource(R.string.goal_context_toggle), Modifier.weight(1f))
        }
        if (expanded) {
            GoalField(R.string.goal_deadline_label, deadline)
            GoalField(R.string.goal_current_state_label, currentState)
            GoalField(R.string.goal_blocker_label, blocker)
            GoalField(R.string.goal_material_links_label, materialLinks)
            GoalField(R.string.goal_material_excerpt_label, materialExcerpt)
            GoalField(R.string.goal_available_minutes_label, availableMinutes)
            Text(stringResource(R.string.goal_material_notice), style = MaterialTheme.typography.bodySmall)
        }
        CommandButton(R.string.prepare_goal, enabled = statement.text.isNotBlank()) { prepare(read()) }
    }
}

/**
 * [read]가 저장한 값과 달라질 때마다 [save]한다. 비교 기준은 저장한 초안 [stored]에서 시작한다.
 * 그래서 다시 만든 화면의 입력이 저장한 초안보다 새로우면 바로 저장하고, 보이는 글자를 예전 값으로 덮지 않는다.
 */
@Composable
private fun <T> AutosaveChanges(stored: T, read: () -> T, save: (T) -> Unit) {
    val latest by rememberUpdatedState(save)
    LaunchedEffect(Unit) {
        var reported = stored
        snapshotFlow(read).collect { if (it != reported) latest(it.also { reported = it }) }
    }
}

@Composable
private fun GoalField(@StringRes label: Int, state: TextFieldState) = LabeledField(stringResource(label), state)

/**
 * 레이블을 입력란 위에 둔다(iOS `goalField`). 떠 있는 레이블은 큰 글꼴에서 테두리와 겹친다.
 * 레이블 위치는 `TextFieldState` 입력란만 정할 수 있다. 레이블은 입력란의 이름으로 읽히고 입력한 글자는 그대로 읽힌다.
 */
@Composable
private fun LabeledField(label: String, state: TextFieldState, placeholder: String? = null) {
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
                // 새로 나타난 질문으로 입력 초점을 옮긴다. TalkBack 초점이 따라오는지는 실제 TalkBack으로 아직 확인하지 않았다. 초점을 받으면 질문이 보이도록 스크롤된다.
                val focus = remember { FocusRequester() }
                Text(question, Modifier.focusRequester(focus).focusable(), style = MaterialTheme.typography.titleMedium)
                LaunchedEffect(question) { focus.requestFocus() }
                key(input?.requestId) {
                    val answer = rememberTextFieldState(input?.text.orEmpty())
                    AutosaveChanges(input?.text.orEmpty(), { answer.text.toString() }) { autosave(it) }
                    LabeledField(stringResource(R.string.goal_question_answer_label), answer, stringResource(R.string.goal_question_prompt))
                    CommandButton(R.string.goal_question_send, enabled = answer.text.isNotBlank()) {
                        val text = answer.text.toString()
                        run { flow.run(Drafts(answer = text)) { flow.answerGoalQuestion(text) } }
                    }
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

/**
 * 카드는 할 일 → 완료 조건 → 예상 시간 순서로 보이고 읽힌다. 그 아래에 설명과 자료, 결과, 결과 입력이 온다.
 * 입력 초안은 카드마다 따로 둔다. 사라지는 카드의 입력이 새 카드의 입력란에 섞이지 않는다.
 */
@Composable
private fun ActionCardContent(
    card: ActionCard,
    smallerStatus: SmallerStatus?,
    commandsInBody: Boolean,
    splitGhost: SplitGhost?,
    onSplitFinished: () -> Unit,
    undone: Boolean,
    suggestionInput: SuggestionInput?,
    smaller: () -> Unit,
    cancel: () -> Unit,
    undo: () -> Unit,
    save: (suspend () -> Unit) -> Unit,
    storageFailed: Boolean,
    flow: ProgressFlow,
    run: (suspend () -> Unit) -> Unit,
    saveDraft: (String, Long) -> Job,
    onResultFocus: (Boolean) -> Unit,
    cardCommands: Mutex,
    draftInputs: MutableMap<Long, String>,
    complete: () -> Unit,
) {
    var draftText by rememberSaveable(card.id) { mutableStateOf(card.draft) }
    var detailsExpanded by rememberSaveable(card.id) { mutableStateOf(false) }
    // 기록하는 동안 버튼을 꺼 연타로 같은 결과가 두 번 기록되지 않게 한다.
    var recording by remember(card.id) { mutableStateOf(false) }
    // 마지막 자동 저장이다. 결과를 기록하기 전에 끝나기를 기다려, 늦은 초안 저장이 기록한 결과를 초안으로 되살리지 않게 한다.
    val lastSave = remember(card.id) { arrayOfNulls<Job>(1) }
    val uriHandler = LocalUriHandler.current
    // 화면을 다시 만들면 입력란은 복구되지만 끝나지 않은 자동 저장은 취소된다. 복구한 입력을 다시 저장한다.
    LaunchedEffect(card.id) {
        if (draftText != card.draft) lastSave[0] = saveDraft(draftText, card.id)
    }
    Column(verticalArrangement = Arrangement.spacedBy(24.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 큰 글꼴에서도 '더 보기'가 48dp를 지키도록 남는 폭은 제목이 줄바꿈해 쓴다.
            Heading(R.string.current_action_title, MaterialTheme.typography.titleLarge, Modifier.weight(1f))
            // 보조 메뉴다. '나중에'는 #354에서 더한다. 지금은 되돌릴 분할 원본이 있을 때만 보인다.
            if (card.origin != null) {
                var menuOpen by remember { mutableStateOf(false) }
                val more = stringResource(R.string.more)
                Box {
                    TextButton({ menuOpen = true }, Modifier.size(48.dp).semantics { contentDescription = more }) {
                        Text("⋯", Modifier.clearAndSetSemantics {}, style = MaterialTheme.typography.titleLarge)
                    }
                    DropdownMenu(menuOpen, { menuOpen = false }) {
                        DropdownMenuItem(
                            { Text(stringResource(R.string.undo_split)) },
                            {
                                menuOpen = false
                                undo()
                            },
                            Modifier.heightIn(min = 48.dp),
                        )
                    }
                }
            }
        }
        if (undone) {
            Text(stringResource(R.string.undo_notice), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        card.origin?.let {
            Text(stringResource(R.string.split_origin, it.task), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Box {
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
                                cardCommands.withLock {
                                    lastSave[0]?.join()
                                    flow.recordResult(text, card.id)
                                    // 기록하는 동안 더 적은 내용은 초안으로 남긴다.
                                    if (draftText == text) {
                                        draftText = ""
                                        draftInputs[card.id] = ""
                                    }
                                }
                            } finally {
                                recording = false
                            }
                        }
                    }
                    if (storageFailed && draftText != card.draft) SecondaryButton(R.string.save_draft_again) { lastSave[0] = saveDraft(draftText, card.id) }
                }
            }
        }
        splitGhost?.let { SplitGhostView(it, onSplitFinished) }
        }
        if (commandsInBody) {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                CommandButton(R.string.complete, onClick = complete)
                if (smallerStatus is SmallerStatus.Question) {
                    QuestionAnswer(smallerStatus.question, suggestionInput, flow, run, save)
                } else {
                    SmallerSection(smallerStatus, smaller, cancel)
                }
            }
        }
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
private fun Heading(@StringRes text: Int, style: androidx.compose.ui.text.TextStyle, modifier: Modifier = Modifier) {
    Text(stringResource(text), modifier.semantics { heading() }, style = style)
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
            is ProgressScreen.CurrentAction -> {
                val oldCard = (old as? ProgressScreen.CurrentAction)?.card
                if (oldCard?.id == new.card.id) {
                    // 초안 자동 저장은 같은 상태를 다시 알리지 않는다. 질문은 초점을 옮겨 읽힌다.
                    if ((old as ProgressScreen.CurrentAction).smaller != new.smaller) when (val smaller = new.smaller) {
                        SmallerStatus.Waiting -> add(resources.getString(R.string.preparing_smaller))
                        is SmallerStatus.Problem -> add(resources.getString(smaller.problem.reason))
                        is SmallerStatus.Question, null -> Unit
                    }
                } else {
                    if (oldCard != null && new.card.origin?.id == oldCard.id) add(resources.getString(R.string.announce_split, oldCard.task))
                    else if (oldCard?.origin?.id == new.card.id) add(resources.getString(R.string.announce_undo))
                    add(resources.getString(R.string.announce_current_action, new.card.task))
                }
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

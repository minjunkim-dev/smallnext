package dev.smallnext.app.progress

import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.data.AppDatabase
import dev.smallnext.app.progress.SuggestionCandidate.Action
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** 제안 대기·실패·취소·다시 시도 화면의 문구·TalkBack 의미·큰 글꼴·구성 변경을 진행 흐름 모듈과 가짜 공급자로 확인한다. */
@RunWith(AndroidJUnit4::class)
class SuggestionStatusScreenTest {
    @get:Rule
    val compose = createAndroidComposeRule<ComponentActivity>()

    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val name = "smallnext-test-${UUID.randomUUID()}.sqlite"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val database by lazy { AppDatabase.open(context, name) }

    private val goal = "통계 기초 단원 하나 학습하기"
    private val first = ProposedAction("학습 자료에서 다음 단원 열기", "단원이 화면에 보인다", 3)

    @After
    fun tearDown() {
        scope.cancel()
        database.close()
        context.deleteDatabase(name)
    }

    /** 목표를 확인해 첫 행동을 기다리는 진행 흐름이다. */
    private fun awaitingFirstAction(provider: ActionSuggestionProvider) = runBlocking {
        ProgressFlow.open(database, goalPreparing(provider), scope).apply {
            prepareGoal(GoalInput(goal))
            awaitSuggestion()
            confirmGoal(goal)
        }
    }

    private fun show(flow: ProgressFlow, fontScale: Float? = null) = compose.setContent {
        val density = LocalDensity.current
        CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale ?: density.fontScale)) {
            SmallnextTheme { CoreFlowScreen(flow) }
        }
    }

    /** 투명도 전환 중에는 이전 화면도 남아 있다. 전환이 끝나 하나만 남을 때까지 기다린다. */
    private fun waitForText(text: String) =
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text)).fetchSemanticsNodes().size == 1 }

    private fun assertAnnounced(message: String) {
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasTestTag(ANNOUNCEMENT) and hasContentDescription(message)).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithTag(ANNOUNCEMENT).assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Polite))
    }

    /** TalkBack이 버튼 이름으로 읽는 노드다. */
    private fun button(text: String) = compose.onNode(
        hasText(text) and hasClickAction() and SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Button),
    )

    /** 모든 글자가 줄 수 제한·말줄임 없이 제약 안에 배치됐는지 확인한다. CoreFlowScreenTest와 같은 기준이다. */
    private fun assertFullyLaidOut(text: String) {
        val results = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText(text).performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(results) }
        val layout = results.single()
        val last = layout.lineCount - 1
        assertFalse(text, layout.didOverflowHeight || layout.isLineEllipsized(last))
        assertEquals(text, text.length, layout.getLineEnd(last))
        assertTrue(text, layout.size.width <= layout.layoutInput.constraints.maxWidth)
    }

    // 실패 이유 7종과 '부적합'·'중단'·'취소'는 iOS `reason(for:)`와 같은 문구다.
    @Test
    fun problemReasonsMatchIosWording() {
        val expected = mapOf(
            SuggestionProblem.Unsuitable to "알맞은 행동을 찾지 못했어요.",
            SuggestionProblem.Interrupted to "행동 제안이 중단됐어요.",
            SuggestionProblem.Cancelled to "행동 제안을 취소했어요.",
            SuggestionProblem.Failure(SuggestionFailure.CONNECTION_LOST) to "연결이 끊겨 행동을 받지 못했어요.",
            SuggestionProblem.Failure(SuggestionFailure.REJECTED) to "행동 제안 요청이 거절됐어요.",
            SuggestionProblem.Failure(SuggestionFailure.UNDECIDABLE) to "다음 행동을 정하지 못했어요.",
            SuggestionProblem.Failure(SuggestionFailure.FAILED) to "행동을 준비하지 못했어요.",
            SuggestionProblem.Failure(SuggestionFailure.TIMED_OUT) to "행동 제안 시간이 초과됐어요.",
            SuggestionProblem.Failure(SuggestionFailure.BUDGET_LIMIT) to "행동 제안 사용 한도에 도달했어요.",
            SuggestionProblem.Failure(SuggestionFailure.UNAVAILABLE) to "지금은 행동 제안을 사용할 수 없어요.",
        )
        assertEquals(SuggestionFailure.entries.size + 3, expected.size)
        for ((problem, text) in expected) assertEquals(text, context.getString(problem.reason))
    }

    // 대기 중 '취소'는 공급자까지 닿고 취소 문장을 안내한다. '다시 시도'는 다시 기다리는 상태를 안내한다.
    @Test
    fun cancelWhileWaitingAnnouncesAndRetryWaitsAgain() {
        val provider = SuspendedProvider()
        val flow = awaitingFirstAction(provider)
        show(flow)
        waitForText("첫 행동을 준비하고 있어요.")
        compose.waitUntil(5_000) { provider.requests.get() == 1 }
        button("다시 시도").assertDoesNotExist()
        button("취소").assertHeightIsAtLeast(48.dp).performScrollTo().performClick()
        waitForText("행동 제안을 취소했어요.")
        assertAnnounced("행동 제안을 취소했어요.")
        runBlocking { flow.awaitSuggestion() }
        assertTrue(provider.cancelled)

        button("취소").assertDoesNotExist()
        button("다시 시도").assertHeightIsAtLeast(48.dp).performScrollTo().performClick()
        waitForText("첫 행동을 준비하고 있어요.")
        assertAnnounced("첫 행동을 준비하고 있어요.")
        compose.waitUntil(5_000) { provider.requests.get() == 2 }
    }

    // 실패하면 짧은 이유를 안내하고 앱은 스스로 다시 요청하지 않는다. 큰 글꼴에서도 문장과 버튼이 잘리지 않는다.
    @Test
    fun failureAnnouncesReasonAndRetriesOnlyOnTapAtLargestFont() {
        val failure = Result.failure<SuggestionCandidate>(SuggestionException(SuggestionFailure.CONNECTION_LOST))
        val provider = ScriptedProvider(listOf(failure, Result.success(Action(first))), gated = true)
        val flow = awaitingFirstAction(provider)
        show(flow, fontScale = 2f)
        waitForText("첫 행동을 준비하고 있어요.")
        assertFullyLaidOut("첫 행동을 준비하고 있어요.")
        button("취소").performScrollTo().assertIsDisplayed().assertHeightIsAtLeast(48.dp)

        provider.release()
        waitForText("연결이 끊겨 행동을 받지 못했어요.")
        assertAnnounced("연결이 끊겨 행동을 받지 못했어요.")
        assertFullyLaidOut("연결이 끊겨 행동을 받지 못했어요.")
        Thread.sleep(50)
        assertEquals(1, provider.requests.size)

        button("다시 시도").performScrollTo().assertIsDisplayed().assertHeightIsAtLeast(48.dp).performClick()
        waitForText("첫 행동을 준비하고 있어요.")
        provider.release()
        waitForText(first.task)
        assertEquals(2, provider.requests.size)
    }

    // 화면 회전처럼 Activity를 다시 만들어도 대기 요청은 취소되거나 다시 전송되지 않는다.
    @Test
    fun recreatingActivityKeepsPendingSuggestion() {
        val provider = ScriptedProvider(Action(first), gated = true)
        val flow = awaitingFirstAction(provider)
        show(flow)
        waitForText("첫 행동을 준비하고 있어요.")
        compose.waitUntil(5_000) { provider.requests.size == 1 }

        compose.activityRule.scenario.recreate()
        compose.activityRule.scenario.onActivity { it.setContent { SmallnextTheme { CoreFlowScreen(flow) } } }
        waitForText("첫 행동을 준비하고 있어요.")
        button("취소").assertExists()
        provider.release()
        waitForText(first.task)
        assertEquals(1, provider.requests.size)
        assertEquals(ProgressScreen.CurrentAction::class, flow.state.value.screen::class)
    }
}

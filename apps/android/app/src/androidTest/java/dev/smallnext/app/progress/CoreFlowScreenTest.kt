package dev.smallnext.app.progress

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import android.view.KeyEvent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.data.AppDatabase
import dev.smallnext.app.progress.SuggestionCandidate.Action
import dev.smallnext.app.progress.SuggestionCandidate.GoalSummary
import dev.smallnext.app.progress.SuggestionCandidate.Question
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

/** Compose 화면의 TalkBack 의미·상호작용·큰 글꼴을 진행 흐름 모듈과 가짜 공급자로 확인한다. */
@RunWith(AndroidJUnit4::class)
class CoreFlowScreenTest {
    @get:Rule
    val compose = createComposeRule()

    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val name = "smallnext-test-${UUID.randomUUID()}.sqlite"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val database by lazy { AppDatabase.open(context, name) }

    private val first = ProposedAction("주간 업무 보고서 문서에서 이번 주에 끝낸 업무 한 줄 적기", "업무 이름이 한 줄 남는다", 3)
    private val second = ProposedAction("적은 업무의 결과를 한 문장으로 적기", "결과 문장이 한 줄 남는다", 8)

    @After
    fun tearDown() {
        scope.cancel()
        database.close()
        context.deleteDatabase(name)
    }

    private fun flow(provider: ActionSuggestionProvider) = runBlocking { ProgressFlow.open(database, provider, scope) }

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

    private fun assertHeading(text: String) =
        compose.onNodeWithText(text).assert(SemanticsMatcher.keyIsDefined(SemanticsProperties.Heading))

    private fun bounds(text: String) = compose.onNodeWithText(text).getUnclippedBoundsInRoot()

    /**
     * 모든 글자가 줄 수 제한·말줄임 없이 제약 안에 배치됐는지 확인한다.
     * `hasVisualOverflow`는 문단 폭(실수)과 크기(정수)의 반올림 차이만으로도 참이 돼 쓰지 않는다.
     */
    private fun assertFullyLaidOut(text: String, unmerged: Boolean = false) {
        val results = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText(text, useUnmergedTree = unmerged).performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(results) }
        val layout = results.single()
        val last = layout.lineCount - 1
        assertFalse(text, layout.didOverflowHeight || layout.isLineEllipsized(last))
        assertEquals(text, text.length, layout.getLineEnd(last))
        assertTrue(text, layout.size.width <= layout.layoutInput.constraints.maxWidth)
    }

    // 핵심 경로의 TalkBack 의미: heading·레이블·상태 안내·카드 읽기 순서·48dp·목표 보기(읽기 전용)·뒤로 가기
    @Test
    fun corePathAnnouncesChangesAndExposesAccessibleStructure() {
        val provider = ScriptedProvider(GoalSummary("보고서 초안이 저장돼 있다"), Action(first), Action(second), gated = true)
        show(flow(provider))
        assertHeading("Smallnext")
        assertHeading("목표를 한 문장으로 적어 주세요.")
        compose.onNodeWithText("목표 한 문장").assertExists()
        compose.onNodeWithText("목표 정리").assertIsNotEnabled()
        compose.onNode(hasSetTextAction()).performTextInput("분기 업무 보고서 초안 쓰기")
        compose.onNodeWithText("목표 정리").assertIsEnabled().assertHeightIsAtLeast(48.dp).performScrollTo().performClick()
        assertAnnounced("목표를 정리하고 있어요.")

        provider.release()
        waitForText("확인하고 시작")
        assertAnnounced("완료 조건을 확인해 주세요.")
        assertHeading("목표 확인")
        compose.onNodeWithText("확인하고 시작").assertHeightIsAtLeast(48.dp).performScrollTo().performClick()
        waitForText("첫 행동을 준비하고 있어요.")
        assertAnnounced("첫 행동을 준비하고 있어요.")

        provider.release()
        waitForText(first.task)
        assertAnnounced("지금 할 행동: ${first.task}")
        assertHeading("지금 할 행동")
        assertHeading(first.task)
        // 카드는 할 일 → 완료 조건 → 예상 시간 순서로 읽힌다(같은 열의 위에서 아래 순서).
        val task = bounds(first.task)
        val doneWhen = bounds(first.doneWhen)
        val estimate = bounds("약 3분 · 예상")
        assertTrue(task.bottom <= doneWhen.top && doneWhen.bottom <= estimate.top)
        compose.onNodeWithTag(PINNED_COMMANDS).assertExists()
        compose.onNodeWithText("완료").assertHeightIsAtLeast(48.dp)
        // 보통 글꼴의 머리 영역은 한 줄이다.
        assertTrue(bounds("목표 보기").top < bounds("Smallnext").bottom)

        compose.onNodeWithText("목표 보기").assertHeightIsAtLeast(48.dp).performClick()
        waitForText("보고서 초안이 저장돼 있다")
        assertHeading("목표")
        compose.onNodeWithText("분기 업무 보고서 초안 쓰기").assertIsDisplayed()
        assertEquals(0, compose.onAllNodes(hasSetTextAction()).fetchSemanticsNodes().size)
        // 시스템 뒤로 가기는 시트를 먼저 닫고 진행 상태를 바꾸지 않는다. 시트 창이 다 열려 초점을 받은 뒤에 누른다.
        compose.waitForIdle()
        InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("보고서 초안이 저장돼 있다")).fetchSemanticsNodes().isEmpty() }
        compose.onNodeWithText(first.task).assertIsDisplayed()

        compose.onNodeWithText("완료").performClick()
        waitForText("다음 행동 대기")
        assertAnnounced("행동을 완료했어요. 다음 행동을 준비하고 있어요.")
        assertHeading("다음 행동 대기")
        provider.release()
        waitForText(second.task)
        assertAnnounced("지금 할 행동: ${second.task}")
    }

    // 선택 입력(최대 글꼴): 펼친 입력란 레이블·자료 안내·자동 저장, 잘못된 입력은 요청 없이 같은 안내를 보이고 읽힌다.
    @Test
    fun optionalInputsAutosaveAndInvalidInputShowsGuidanceWithoutRequest() {
        val provider = ScriptedProvider(GoalSummary("화분이 새 자리에 있다"))
        val flow = flow(provider)
        show(flow, fontScale = 2f)
        assertEquals(1, compose.onAllNodes(hasSetTextAction()).fetchSemanticsNodes().size)
        val toggle = compose.onNodeWithText("아는 맥락 보태기 (선택)")
        toggle.assertHeightIsAtLeast(48.dp).assert(SemanticsMatcher.keyIsDefined(SemanticsActions.Expand)).performScrollTo().performClick()
        toggle.assert(SemanticsMatcher.keyIsDefined(SemanticsActions.Collapse))
        val labels = listOf(
            "기한 (선택)", "현재 상태 (선택)", "막힌 점 (선택)", "자료 링크 (선택, 한 줄에 하나)", "고른 발췌·요약 (선택)", "지금 쓸 수 있는 시간 (선택, 분)",
        )
        for (label in labels) {
            compose.onNode(hasSetTextAction() and hasText(label)).performScrollTo()
            assertFullyLaidOut(label, unmerged = true)
        }
        val notice = "자료는 링크와 직접 고른 발췌·요약만 보내요. 링크의 내용은 자동으로 읽지 않아요."
        compose.onNodeWithText(notice).performScrollTo()
        assertFullyLaidOut(notice)

        compose.onNode(hasSetTextAction() and hasText("목표 한 문장")).performTextInput("화분 옮기기")
        compose.onNode(hasSetTextAction() and hasText("자료 링크 (선택, 한 줄에 하나)")).performScrollTo().performTextInput("file:///tmp/plant")
        compose.waitUntil(5_000) { flow.state.value.goalInput == GoalInput("화분 옮기기", materialLinks = "file:///tmp/plant") }
        compose.onNodeWithText("목표 정리").performScrollTo().performClick()
        val problem = "자료 링크는 http:// 또는 https://로 입력해 주세요. 시간은 1 이상의 정수로 입력해 주세요."
        assertAnnounced(problem)
        compose.onNodeWithText(problem).performScrollTo().assertIsDisplayed()
        assertFullyLaidOut(problem)
        assertEquals(ProgressScreen.GoalInput, flow.state.value.screen)
        assertTrue(provider.requests.isEmpty())

        // 고쳐 입력하면 안내가 사라지고 요청한다.
        compose.onNode(hasSetTextAction() and hasText("자료 링크 (선택, 한 줄에 하나)")).performScrollTo().performTextClearance()
        compose.onAllNodes(hasText(problem)).assertCountEquals(0)
        compose.onNodeWithText("목표 정리").performScrollTo().performClick()
        waitForText("확인하고 시작")
        assertEquals(listOf(SuggestionKind.GOAL_PREPARATION), provider.requests.map { it.kind })
    }

    // 다시 연 목표 입력 초안에 선택 입력이 있으면 펼쳐서 보여준다. 보내질 자료와 입력 오류가 가려지지 않는다.
    @Test
    fun restoredOptionalDraftShowsOptionalFields() {
        val flow = flow(UnavailableSuggestionProvider)
        runBlocking { flow.updateGoalInput(GoalInput("화분 옮기기", materialLinks = "file:///tmp/plant")) }
        show(flow)
        compose.onNode(hasSetTextAction() and hasText("자료 링크 (선택, 한 줄에 하나)")).performScrollTo().assertIsDisplayed()
        compose.onNode(hasText("file:///tmp/plant")).assertExists()
    }

    // 목표 확인 질문(최대 글꼴): 질문으로 초점이 옮겨지고, 답 입력란 레이블과 답 초안 자동 저장을 확인한다.
    @Test
    fun goalQuestionTakesFocusAndAnswerDraftIsSaved() {
        val question = "무엇을 정리하려고 하나요? 책상 위 서류인지 컴퓨터의 파일인지 알려 주세요."
        val provider = ScriptedProvider(Question(question), GoalSummary("서류를 정리했다"))
        val flow = flow(provider)
        runBlocking {
            flow.prepareGoal(GoalInput("정리하기"))
            flow.awaitSuggestion()
        }
        show(flow, fontScale = 2f)
        waitForText(question)
        compose.onNodeWithText(question).assertIsFocused()
        assertFullyLaidOut(question)
        compose.onNode(hasSetTextAction() and hasText("목표 확인 질문 답")).performScrollTo().performTextInput("책상 위 서류")
        compose.waitUntil(5_000) { flow.state.value.suggestionInput?.text == "책상 위 서류" }
        compose.onNodeWithText("답 보내기").assertHeightIsAtLeast(48.dp).performScrollTo().performClick()
        waitForText("확인하고 시작")
        assertEquals(listOf(GoalAnswer(question, "책상 위 서류")), provider.requests[1].context.answers)
    }

    // 큰 글꼴: 머리 영역을 세로로 쌓고 하단 고정 버튼을 본문으로 옮긴다. 최대 배율에서 카드 글자가 잘리지 않는다.
    @Test
    fun largestFontStacksHeaderAndMovesCompleteIntoBody() {
        val provider = ScriptedProvider(Action(first))
        val flow = flow(goalPreparing(provider))
        runBlocking {
            flow.prepareGoal(GoalInput("분기 업무 보고서 초안 쓰기"))
            flow.awaitSuggestion()
            flow.confirmGoal("분기 업무 보고서 초안 쓰기")
            flow.awaitSuggestion()
        }
        show(flow, fontScale = 2f)
        waitForText(first.task)
        compose.onNodeWithTag(PINNED_COMMANDS).assertDoesNotExist()
        assertTrue(bounds("목표 보기").top >= bounds("Smallnext").bottom)
        for (text in listOf(first.task, first.doneWhen, "약 3분 · 예상")) {
            assertFullyLaidOut(text)
        }
        compose.onNodeWithText("완료").performScrollTo().assertIsDisplayed().assertHeightIsAtLeast(48.dp).performClick()
        waitForText("다음 행동 대기")
    }

    // 구성 변경(회전 등)으로 화면을 다시 만들어도 대기 요청은 앱 수명의 진행 흐름에서 이어진다.
    @Test
    fun pendingSuggestionSurvivesRecreatingTheScreen() {
        val provider = HeldProvider(Action(first))
        val flow = flow(goalPreparing(provider))
        runBlocking {
            flow.prepareGoal(GoalInput("통계 기초 단원 하나 학습하기"))
            flow.awaitSuggestion()
            flow.confirmGoal("통계 기초 단원 하나 학습하기")
        }
        val restoration = StateRestorationTester(compose)
        restoration.setContent { SmallnextTheme { CoreFlowScreen(flow) } }
        waitForText("첫 행동을 준비하고 있어요.")
        restoration.emulateSavedInstanceStateRestore()
        waitForText("첫 행동을 준비하고 있어요.")
        provider.release()
        waitForText(first.task)
        assertEquals(1, provider.requests.get())
    }
}

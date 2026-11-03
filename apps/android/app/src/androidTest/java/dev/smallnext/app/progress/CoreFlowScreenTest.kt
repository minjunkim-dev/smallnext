package dev.smallnext.app.progress

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.UriHandler
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.performTextReplacement
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
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import android.view.KeyEvent
import android.view.View
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.data.AppDatabase
import dev.smallnext.app.progress.SuggestionCandidate.Action
import dev.smallnext.app.progress.SuggestionCandidate.GoalSummary
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

    private val openedLinks = mutableListOf<String>()
    private lateinit var view: View

    private fun show(flow: ProgressFlow, fontScale: Float? = null) = compose.setContent {
        val density = LocalDensity.current
        view = LocalView.current
        val links = object : UriHandler {
            override fun openUri(uri: String) {
                openedLinks.add(uri)
            }
        }
        CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale ?: density.fontScale), LocalUriHandler provides links) {
            SmallnextTheme { CoreFlowScreen(flow) }
        }
    }

    private fun sql(statement: String) = database.openHelper.writableDatabase.execSQL(statement)

    private fun count(query: String) = database.openHelper.writableDatabase.query(query).use { it.moveToFirst(); it.getLong(0) }

    private val resultField get() = compose.onNode(hasText("행동 결과 입력") and hasSetTextAction())

    /** 목표를 확인하고 첫 행동을 받은 흐름이다. */
    private fun flowWithCard(vararg actions: ProposedAction) = flow(goalPreparing(ScriptedProvider(*actions.map(::Action).toTypedArray()))).also {
        runBlocking {
            it.prepareGoal(GoalInput("분기 업무 보고서 초안 쓰기"))
            it.awaitSuggestion()
            it.confirmGoal("분기 업무 보고서 초안 쓰기")
            it.awaitSuggestion()
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
    private fun assertFullyLaidOut(text: String) {
        val results = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText(text).performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(results) }
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
        // 시트는 읽기 전용이다. 입력란은 시트 뒤 카드의 결과 입력란뿐이다.
        assertEquals(0, compose.onAllNodes(hasSetTextAction() and !hasText("행동 결과 입력")).fetchSemanticsNodes().size)
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

    // 행동 결과·초안·카드 상세(#351): 대상·설명과 자료·앞선 결과, 링크 열기, 초안 자동 저장, '결과 남기기', 다음 카드의 빈 입력란
    @Test
    fun cardShowsDetailsSavesDraftAndRecordsResult() {
        val initial = first.copy(targetName = "업무 보고서")
        val next = second.copy(
            targetName = "업무 보고서",
            targetDescription = "이번 주 업무를 적은 문서",
            materialLinks = listOf("https://example.com/report"),
        )
        val third = ProposedAction("보고서 제목 한 줄 정하기", "제목이 적혀 있다", 2)
        val flow = flowWithCard(initial, next, third)
        runBlocking {
            val card = (flow.state.value.screen as ProgressScreen.CurrentAction).card
            flow.recordResult("확인한 기간: 10월 첫째 주", card.id)
            flow.complete(card.id)
            flow.awaitSuggestion()
        }
        show(flow)
        waitForText(next.task)
        compose.onNodeWithText("대상: 업무 보고서").assertIsDisplayed()
        compose.onNodeWithText("앞서 남긴 결과").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("확인한 기간: 10월 첫째 주").assertIsDisplayed()

        // 설명과 자료는 필요할 때만 펼친다. 링크는 기기 브라우저로 연다.
        compose.onNodeWithText("이번 주 업무를 적은 문서").assertDoesNotExist()
        val details = compose.onNodeWithText("설명과 자료").performScrollTo().assertHeightIsAtLeast(48.dp)
        details.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "접힘")).performClick()
        details.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "펼침"))
        compose.onNodeWithText("이번 주 업무를 적은 문서").assertIsDisplayed()
        compose.onNodeWithText("https://example.com/report").performScrollTo().assertHeightIsAtLeast(48.dp).performClick()
        assertEquals(listOf("https://example.com/report"), openedLinks)

        // 입력 초안은 결과로 바뀌지 않고 저장된다.
        compose.onNodeWithText("결과 남기기").performScrollTo().assertIsNotEnabled()
        resultField.performScrollTo().performTextInput("보고서 첫 줄 작성")
        compose.waitUntil(5_000) { count("SELECT COUNT(*) FROM action_note WHERE is_draft AND body = '보고서 첫 줄 작성'") == 1L }
        assertEquals(0L, count("SELECT COUNT(*) FROM action_note WHERE NOT is_draft AND body = '보고서 첫 줄 작성'"))
        compose.onNodeWithText("작성 중인 내용은 자동 저장돼요.").assertExists()

        // 키보드가 열리는 중이면 터치 주입이 키보드에 떨어질 수 있어 클릭 동작을 직접 실행한다.
        compose.onNodeWithText("결과 남기기").performScrollTo().assertIsEnabled().assertHeightIsAtLeast(48.dp)
            .performSemanticsAction(SemanticsActions.OnClick)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("이 행동에 남긴 결과")).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("보고서 첫 줄 작성").assertExists()
        resultField.assert(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString("")))
        assertEquals(0L, count("SELECT COUNT(*) FROM action_note WHERE is_draft"))

        // 남은 초안은 이 카드에 남고 다음 카드의 입력란에 섞이지 않는다.
        resultField.performScrollTo().performTextInput("다음 카드에 섞이면 안 되는 초안")
        compose.waitUntil(5_000) { count("SELECT COUNT(*) FROM action_note WHERE is_draft") == 1L }
        // 키보드가 열려 있으면 '완료'는 본문 아래쪽에 있다. 터치 주입이 키보드에 떨어지지 않게 클릭 동작을 직접 실행한다.
        compose.onNodeWithText("완료").performSemanticsAction(SemanticsActions.OnClick)
        waitForText(third.task)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("행동 결과 입력") and hasSetTextAction()).fetchSemanticsNodes().size == 1 }
        resultField.assert(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString("")))
        compose.onNodeWithText("앞서 남긴 결과").assertDoesNotExist()
        assertEquals(1L, count("SELECT COUNT(*) FROM action_note WHERE is_draft"))
    }

    // '결과 남기기'를 다시 그리기 전에 두 번 눌러도 결과는 하나만 기록된다.
    @Test
    fun doubleTapOnRecordResultRecordsOnce() {
        val flow = flowWithCard(first)
        show(flow)
        waitForText(first.task)
        resultField.performScrollTo().performTextInput("한 번만 남길 결과")
        compose.waitUntil(5_000) { count("SELECT COUNT(*) FROM action_note WHERE is_draft") == 1L }
        val click = compose.onNodeWithText("결과 남기기").fetchSemanticsNode().config[SemanticsActions.OnClick].action!!
        compose.runOnUiThread {
            click()
            click()
        }
        // 두 탭의 명령이 차례 대기열에 들어간 뒤, 뒤에 넣은 명령이 끝나면 두 명령 모두 끝났다.
        compose.waitForIdle()
        runBlocking { flow.retrySuggestion() }
        assertEquals(1L, count("SELECT COUNT(*) FROM action_note WHERE NOT is_draft"))
        assertEquals(0L, count("SELECT COUNT(*) FROM action_note WHERE is_draft"))
    }

    // 초안 저장 실패: 문구를 보이고 첫 실패만 알린다. 입력은 그대로 두고 '입력 다시 저장'으로 다시 저장한다.
    @Test
    fun draftSaveFailureIsShownAnnouncedOnceAndCanBeRetried() {
        val flow = flowWithCard(first)
        show(flow)
        waitForText(first.task)
        sql("CREATE TRIGGER reject_note BEFORE INSERT ON action_note BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        resultField.performScrollTo().performTextInput("가")
        assertAnnounced("저장하지 못했어요. 다시 시도해 주세요.")
        resultField.performTextReplacement("가나")
        // 명령은 차례로 실행된다. 뒤에 넣은 저장이 끝나면 화면의 두 번째 저장 시도도 끝났다.
        runBlocking { runCatching { flow.updateDraft("가나", (flow.state.value.screen as ProgressScreen.CurrentAction).card.id) } }
        compose.waitForIdle()
        // 같은 안내를 다시 보내면 끝에 보이지 않는 문자가 붙는다. 붙지 않았으면 한 번만 알린 것이다.
        compose.onNodeWithTag(ANNOUNCEMENT).assert(hasContentDescription("저장하지 못했어요. 다시 시도해 주세요."))
        compose.onNodeWithText("저장하지 못했어요. 다시 시도해 주세요.").assertExists()
        resultField.assert(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString("가나")))

        sql("DROP TRIGGER reject_note")
        compose.onNodeWithText("입력 다시 저장").performScrollTo().assertHeightIsAtLeast(48.dp).performClick()
        compose.waitUntil(5_000) { count("SELECT COUNT(*) FROM action_note WHERE is_draft AND body = '가나'") == 1L }
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("저장하지 못했어요. 다시 시도해 주세요.")).fetchSemanticsNodes().isEmpty() }
        compose.onNodeWithText("입력 다시 저장").assertDoesNotExist()
    }

    // 결과 입력란에 초점이 있고 키보드가 열리면 '완료'를 본문으로 옮긴다. 본문은 키보드 inset만큼 줄어 버튼이 키보드 위에 보인다.
    @Test
    fun keyboardOnResultFieldMovesCommandsIntoBodyAboveKeyboard() {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        fun shell(command: String) = automation.executeShellCommand(command).use { android.os.ParcelFileDescriptor.AutoCloseInputStream(it).reader().readText().trim() }
        val previous = shell("settings get secure show_ime_with_hard_keyboard")
        shell("settings put secure show_ime_with_hard_keyboard 1")
        try {
            show(flowWithCard(first))
            waitForText(first.task)
            compose.onNodeWithTag(PINNED_COMMANDS).assertExists()
            resultField.performScrollTo().performClick()
            fun imeBottom() = ViewCompat.getRootWindowInsets(view)?.getInsets(WindowInsetsCompat.Type.ime())?.bottom ?: 0
            compose.waitUntil(10_000) { imeBottom() > 0 }
            compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag(PINNED_COMMANDS)).fetchSemanticsNodes().isEmpty() }
            for (text in listOf("결과 남기기", "완료")) {
                compose.onNodeWithText(text).performScrollTo().assertIsDisplayed()
                val bottom = with(compose.density) { bounds(text).bottom.toPx() }
                assertTrue(text, bottom <= view.height - imeBottom())
            }
        } finally {
            shell(if (previous == "null") "settings delete secure show_ime_with_hard_keyboard" else "settings put secure show_ime_with_hard_keyboard $previous")
        }
    }

    // 최대 글꼴: 대상·설명과 자료·결과·입력 안내가 잘리지 않고 버튼은 48dp 이상이다.
    @Test
    fun largestFontKeepsCardDetailsAndResultControlsReadable() {
        val flow = flowWithCard(
            first.copy(
                targetName = "업무 보고서",
                targetDescription = "이번 주 업무를 적은 문서",
                materialLinks = listOf("https://example.com/report"),
            ),
        )
        runBlocking {
            val card = (flow.state.value.screen as ProgressScreen.CurrentAction).card
            flow.recordResult("확인한 기간: 10월 첫째 주", card.id)
        }
        show(flow, fontScale = 2f)
        waitForText(first.task)
        compose.onNodeWithText("설명과 자료").performScrollTo().assertHeightIsAtLeast(48.dp).performClick()
        compose.onNodeWithText("https://example.com/report").performScrollTo().assertHeightIsAtLeast(48.dp)
        for (text in listOf("대상: 업무 보고서", "이번 주 업무를 적은 문서", "이 행동에 남긴 결과", "확인한 기간: 10월 첫째 주", "작성 중인 내용은 자동 저장돼요.")) {
            compose.onNodeWithText(text).performScrollTo()
            assertFullyLaidOut(text)
        }
        compose.onNodeWithText("결과 남기기").performScrollTo().assertHeightIsAtLeast(48.dp)
        resultField.performScrollTo().assertHeightIsAtLeast(48.dp)
    }
}

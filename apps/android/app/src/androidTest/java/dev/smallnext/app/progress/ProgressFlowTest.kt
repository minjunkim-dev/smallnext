package dev.smallnext.app.progress

import android.database.sqlite.SQLiteException
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.data.AppDatabase
import dev.smallnext.app.progress.SuggestionCandidate.Action
import dev.smallnext.app.progress.SuggestionCandidate.GoalSummary
import dev.smallnext.app.progress.SuggestionCandidate.Question
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** 진행 흐름 모듈의 공개 명령과 화면 상태를 실제 Room 임시 DB와 가짜 공급자로 확인한다. 이름은 iOS `ProgressFlowTests`와 같다. */
@RunWith(AndroidJUnit4::class)
class ProgressFlowTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val name = "smallnext-test-${UUID.randomUUID()}.sqlite"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val databases = mutableListOf<AppDatabase>()
    private var probeDatabase: AppDatabase? = null
    /** 직접 조회하는 DB다. [closeAll]로 닫혔으면 다시 연다. */
    private val probe get() = (probeDatabase?.takeIf { it.isOpen } ?: open().also { probeDatabase = it }).openHelper.writableDatabase

    private val first = ProposedAction("관련 메모 하나 열기", "메모가 화면에 열려 있다", 3)
    private val second = ProposedAction("첫 문단 한 줄 쓰기", "문장 한 줄이 저장돼 있다", 5)
    private val third = ProposedAction("제목 한 줄 정하기", "제목이 적혀 있다", 2)
    private val smaller = ProposedAction("메모 제목만 확인하기", "메모 제목을 읽었다", 1)
    private val question = "가장 먼저 막히는 지점은 무엇인가요?"

    @After
    fun tearDown() {
        scope.cancel()
        databases.forEach { it.close() }
        context.deleteDatabase(name)
    }

    private fun open() = AppDatabase.open(context, name).also(databases::add)

    /** 목표 준비 요청은 [goalPreparing]이 답한다. 준비 결과를 직접 검사하는 테스트는 `preparing = false`를 쓴다. */
    private suspend fun makeFlow(provider: ActionSuggestionProvider, preparing: Boolean = true) =
        ProgressFlow.open(open(), if (preparing) goalPreparing(provider) else provider, scope)

    /** 앱 종료처럼 열린 DB를 모두 닫는다. 다음 [makeFlow]가 같은 파일을 다시 연다. */
    private fun closeAll() {
        databases.forEach { it.close() }
        databases.clear()
    }

    /** 사용자 경로로 목표를 준비하고 완료 조건을 확인한다. 첫 행동 요청이 시작된 상태로 끝난다. */
    private suspend fun startGoal(flow: ProgressFlow, statement: String) {
        flow.prepareGoal(GoalInput(statement))
        flow.awaitSuggestion()
        flow.confirmGoal(statement)
    }

    private fun ProgressFlow.card() = (state.value.screen as ProgressScreen.CurrentAction).card

    private suspend fun firstCard(flow: ProgressFlow): ActionCard {
        startGoal(flow, "주간 업무 보고서 초안 쓰기")
        flow.awaitSuggestion()
        return flow.card()
    }

    private fun count(sql: String) = probe.query(sql).use { it.moveToFirst(); it.getLong(0) }

    private fun status(ofTask: String): String? =
        probe.query("SELECT status FROM action WHERE task = ?", arrayOf(ofTask)).use { if (it.moveToFirst()) it.getString(0) else null }

    /** 요청에 담는 현재 행동은 할 일·완료 기준·예상 시간만 있다. iOS `card(_:)`와 같다. */
    private fun card(action: ProposedAction) = ProposedAction(action.task, action.doneWhen, action.estimatedMinutes)

    private fun ProgressFlow.smaller() = (state.value.screen as ProgressScreen.CurrentAction).smaller

    private fun current(card: ActionCard, smaller: SmallerStatus? = null) = ProgressScreen.CurrentAction(card, smaller)

    private suspend fun failure(command: suspend () -> Unit) = runCatching { command() }.exceptionOrNull()

    /** iOS `startNewGoal`은 아직 Android에 없다. 선택한 목표만 풀고 새 흐름을 열어 목표 입력부터 시작한다. */
    private suspend fun newGoalFlow(provider: ActionSuggestionProvider): ProgressFlow {
        probe.execSQL("DELETE FROM app_metadata WHERE `key` = 'selected_goal_id'")
        return makeFlow(provider)
    }

    /** 공급자가 요청을 받을 때까지 기다린다. 취소·늦은 응답이 실제로 공급자 안에서 일어나게 한다. */
    private suspend fun awaitRequest(requests: AtomicInteger) = withTimeout(5_000) { while (requests.get() == 0) delay(10) }

    private fun failures(vararg failures: SuggestionFailure) = failures.map { Result.failure<SuggestionCandidate>(SuggestionException(it)) }

    @Test
    fun testBlankGoalCannotStart() = runBlocking {
        val provider = ScriptedProvider(Action(first))
        val flow = makeFlow(provider, preparing = false)
        val error = failure { flow.prepareGoal(GoalInput(statement = " \n ")) }
        assertEquals(ProgressFlowException.Reason.EMPTY_GOAL, (error as ProgressFlowException).reason)
        assertEquals(ProgressScreen.GoalInput, flow.state.value.screen)
        assertTrue(provider.requests.isEmpty())
        assertEquals(0L, count("SELECT COUNT(*) FROM goal"))
    }

    @Test
    fun testGoalPreparationCannotApplyActionBeforeConfirmation() = runBlocking {
        val provider = ScriptedProvider(Action(first), GoalSummary("메모를 정리했다"))
        val flow = makeFlow(provider, preparing = false)
        flow.prepareGoal(GoalInput(statement = "메모 정리"))
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.PreparingGoal(null, null, SuggestionProblem.Unsuitable), flow.state.value.screen)
        assertTrue(failure { flow.confirmGoal("확인되지 않은 조건") } is ProgressFlowException)
        flow.retrySuggestion()
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.PreparingGoal(null, "메모를 정리했다", null), flow.state.value.screen)
        assertNull(flow.state.value.goal?.context?.currentState)
        assertNull(flow.state.value.goal?.completionCriteria)
        assertEquals(0L, count("SELECT COUNT(*) FROM action"))
    }

    // 선택 입력과 목표 확인 질문(#350)

    @Test
    fun testGoalInputDraftSurvivesReopenBeforeSubmission() = runBlocking {
        val input = GoalInput(
            "화분 옮기기", "이번 주", "화분은 골랐다", "흙이 있는지 모른다", "https://example.com/plant", "사용자가 고른 요약", "15",
        )
        val flow = makeFlow(UnavailableSuggestionProvider)
        flow.updateGoalInput(input)
        assertEquals(ProgressScreen.GoalInput, flow.state.value.screen)
        closeAll()
        val reopened = makeFlow(UnavailableSuggestionProvider)
        assertEquals(input, reopened.state.value.goalInput)
        assertNull(reopened.state.value.goal)
    }

    @Test
    fun testGoalContextIsSentAndFirstActionWaitsForConfirmation() = runBlocking {
        val provider = ScriptedProvider(GoalSummary("화분 하나를 옮겼다"), Action(first))
        val flow = makeFlow(provider, preparing = false)
        flow.updateGoalInput(
            GoalInput(" 화분 옮기기 ", "이번 주", "화분은 골랐다", "흙이 있는지 모른다", "https://example.com/plant", "고른 발췌만 보낸다", "15"),
        )
        flow.prepareGoal()
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.PreparingGoal(null, "화분 하나를 옮겼다", null), flow.state.value.screen)
        assertNull(flow.state.value.goal?.completionCriteria)
        assertEquals(listOf(SuggestionKind.GOAL_PREPARATION), provider.requests.map { it.kind })
        val context = provider.requests[0].context
        assertEquals("화분은 골랐다", context.currentState)
        assertEquals("이번 주", context.deadline)
        assertEquals(listOf("https://example.com/plant"), context.materialLinks)
        assertEquals("고른 발췌만 보낸다", context.materialExcerpt)
        assertEquals(15, context.availableMinutes)
        assertEquals("흙이 있는지 모른다", provider.requests[0].blocker)
        flow.confirmGoal("화분 하나가 새 자리에 있다")
        flow.awaitSuggestion()
        assertEquals(first.task, flow.card().task)
        assertEquals(listOf(SuggestionKind.GOAL_PREPARATION, SuggestionKind.FIRST_ACTION), provider.requests.map { it.kind })
        assertEquals("화분 하나가 새 자리에 있다", provider.requests[1].completionCriteria)
        assertEquals(context, provider.requests[1].context)
        closeAll()
        val reopened = makeFlow(UnavailableSuggestionProvider, preparing = false)
        assertEquals("화분 옮기기", reopened.state.value.goal?.statement)
        assertEquals("화분 하나가 새 자리에 있다", reopened.state.value.goal?.completionCriteria)
        assertEquals(context, reopened.state.value.goal?.context)
    }

    @Test
    fun testGoalQuestionAnswerSurvivesReopenAndIsNotAskedAgain() = runBlocking {
        val question = "무엇을 정리하려고 하나요?"
        val flow = makeFlow(ScriptedProvider(Question(question)), preparing = false)
        flow.updateGoalInput(GoalInput("정리하기"))
        flow.prepareGoal()
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.PreparingGoal(question, null, null), flow.state.value.screen)
        closeAll()
        val provider = ScriptedProvider(Question(question), GoalSummary("화분 자리를 정했다"))
        val reopened = makeFlow(provider, preparing = false)
        assertEquals(ProgressScreen.PreparingGoal(question, null, null), reopened.state.value.screen)
        assertTrue(failure { reopened.answerGoalQuestion(" \n") } is ProgressFlowException)
        reopened.answerGoalQuestion("화분 자리")
        reopened.awaitSuggestion()
        assertEquals(ProgressScreen.PreparingGoal(null, null, SuggestionProblem.Unsuitable), reopened.state.value.screen)
        reopened.retrySuggestion()
        reopened.awaitSuggestion()
        assertEquals(ProgressScreen.PreparingGoal(null, "화분 자리를 정했다", null), reopened.state.value.screen)
        assertEquals(listOf(SuggestionKind.GOAL_PREPARATION, SuggestionKind.GOAL_PREPARATION), provider.requests.map { it.kind })
        assertEquals(listOf(GoalAnswer(question, "화분 자리")), provider.requests[1].context.answers)
        assertNull(provider.requests[1].context.currentState)
        assertNull(provider.requests[1].blocker)
        closeAll()
        val again = makeFlow(UnavailableSuggestionProvider, preparing = false)
        assertEquals(reopened.state.value.screen, again.state.value.screen)
        assertEquals(provider.requests[1].context.answers, again.state.value.goal?.context?.answers)
        assertNull(again.state.value.goal?.completionCriteria)
    }

    // iOS testSuggestionInputDraftsSurviveGoalSwitchAndReopenAndRejectStaleInput 중 목표 전환을 뺀 부분이다(목표 전환은 #357).
    @Test
    fun testSuggestionInputDraftsSurviveReopenAndRejectStaleInput() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Question("어떤 자료인가요?"), GoalSummary("자료를 정리했다")), preparing = false)
        flow.prepareGoal(GoalInput("학습 자료 정리"))
        flow.awaitSuggestion()
        val questionRequest = flow.state.value.suggestionInput!!.requestId
        flow.updateSuggestionInput("질문 답을 작성 중", questionRequest)
        closeAll()
        val reopened = makeFlow(ScriptedProvider(Action(first)), preparing = false)
        assertEquals(SuggestionInput(questionRequest, "질문 답을 작성 중"), reopened.state.value.suggestionInput)
        reopened.run(Drafts(answer = "자료 목록")) { reopened.answerGoalQuestion("자료 목록") }
        assertNull(reopened.state.value.suggestionInput)
        reopened.awaitSuggestion()
        closeAll()
        val provider = ScriptedProvider(GoalSummary("자료를 정리했다"), Action(first))
        val again = makeFlow(provider, preparing = false)
        again.retrySuggestion()
        again.awaitSuggestion()
        val criteriaRequest = again.state.value.suggestionInput!!.requestId
        assertTrue(failure { again.updateSuggestionInput("다른 질문의 늦은 입력", questionRequest) } is ProgressFlowException)
        again.run(Drafts(completionCriteria = "자료 목록이 한 곳에 있다")) {}
        closeAll()
        val last = makeFlow(provider, preparing = false)
        assertEquals(SuggestionInput(criteriaRequest, "자료 목록이 한 곳에 있다"), last.state.value.suggestionInput)
        last.confirmGoal("자료 목록이 한 곳에 있다")
        last.awaitSuggestion()
        assertNull(last.state.value.suggestionInput)
        assertTrue(failure { last.updateSuggestionInput("이전 완료 조건", criteriaRequest) } is ProgressFlowException)
        assertEquals("자료 목록이 한 곳에 있다", last.state.value.goal?.completionCriteria)
    }

    @Test
    fun testInvalidOptionalInputStaysInDraftWithoutRequestingProvider() = runBlocking {
        val provider = ScriptedProvider(GoalSummary("정리를 마쳤다"))
        val flow = makeFlow(provider, preparing = false)
        for (input in listOf(
            GoalInput("정리", materialLinks = "file:///private/tmp/file"),
            GoalInput("정리", availableMinutes = "-3"),
            GoalInput("정리", availableMinutes = "abc"),
        )) {
            flow.updateGoalInput(input)
            val error = failure { flow.prepareGoal() }
            assertEquals(ProgressFlowException.Reason.INVALID_GOAL_CONTEXT, (error as ProgressFlowException).reason)
            assertEquals(input, flow.state.value.goalInput)
            assertEquals(ProgressScreen.GoalInput, flow.state.value.screen)
        }
        assertTrue(provider.requests.isEmpty())
    }

    @Test
    fun testWhitespaceOnlyOptionalLinkIsTreatedAsEmpty() = runBlocking {
        val provider = ScriptedProvider(GoalSummary("메모를 정리했다"))
        val flow = makeFlow(provider, preparing = false)
        flow.updateGoalInput(GoalInput("메모 정리", materialLinks = " \n\t "))
        flow.prepareGoal()
        flow.awaitSuggestion()
        assertEquals(1, provider.requests.size)
        assertTrue(provider.requests[0].context.materialLinks.isEmpty())
    }

    @Test
    fun testNonWebMaterialLinkIsRejected() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first.copy(materialLinks = listOf("file:///private/tmp/report")))))
        startGoal(flow, "보고서 정리")
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.AwaitingFirstAction("보고서 정리", SuggestionProblem.Unsuitable), flow.state.value.screen)
    }

    @Test
    fun testRunSavesGoalInputDraftBeforeCommand() = runBlocking {
        val flow = makeFlow(UnavailableSuggestionProvider, preparing = false)
        flow.run(Drafts(GoalInput("자료 정리"))) { flow.prepareGoal() }
        assertEquals("자료 정리", flow.state.value.goal?.statement)
    }

    // iOS는 행동 메모 초안과 '나중에'로 확인한다. 둘은 #351·#355에서 생겨 여기서는 목표 입력 초안으로 같은 계약을 확인한다.
    @Test
    fun testRunDoesNotRunCommandWhenDraftSaveFails() = runBlocking {
        val flow = makeFlow(UnavailableSuggestionProvider, preparing = false)
        probe.execSQL("CREATE TRIGGER reject_draft BEFORE INSERT ON app_metadata BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        var ran = false
        assertTrue(failure { flow.run(Drafts(GoalInput("다시 볼 목표"))) { ran = true } } is SQLiteException)
        assertFalse(ran)
        assertEquals(GoalInput(), flow.state.value.goalInput)
        probe.execSQL("DROP TRIGGER reject_draft")
        flow.run(Drafts(GoalInput("다시 볼 목표"))) { flow.prepareGoal() }
        assertEquals("다시 볼 목표", flow.state.value.goal?.statement)
    }

    @Test
    fun testGoalToFirstActionToCompletionToNextActionSurvivesReopen() = runBlocking {
        val provider = ScriptedProvider(Action(first), Action(second), gated = true)
        val flow = makeFlow(provider)
        assertEquals(ProgressScreen.GoalInput, flow.state.value.screen)

        startGoal(flow, "  주간 업무 보고서 초안 쓰기 ")
        assertEquals(ProgressScreen.AwaitingFirstAction("주간 업무 보고서 초안 쓰기", null), flow.state.value.screen)
        provider.release()
        flow.awaitSuggestion()
        assertEquals(ActionCard(flow.card().id, first.task, first.doneWhen, first.estimatedMinutes), flow.card())

        val firstCard = flow.card()
        flow.complete(firstCard.id)
        flow.complete(firstCard.id)
        assertEquals(ProgressScreen.AwaitingNextAction(null), flow.state.value.screen)
        provider.release()
        flow.awaitSuggestion()
        val secondCard = flow.card()
        assertEquals(second.task, secondCard.task)
        assertEquals(listOf(SuggestionKind.FIRST_ACTION, SuggestionKind.NEXT_ACTION), provider.requests.map { it.kind })
        assertEquals("주간 업무 보고서 초안 쓰기", provider.requests[0].goal)
        assertEquals(listOf(first.task), provider.requests[1].completedTasks)

        closeAll()
        val nextProvider = ScriptedProvider(Action(third))
        val reopened = makeFlow(nextProvider)
        assertEquals(ProgressScreen.CurrentAction(secondCard), reopened.state.value.screen)
        assertEquals("주간 업무 보고서 초안 쓰기", reopened.state.value.goal?.completionCriteria)
        reopened.complete(secondCard.id)
        reopened.awaitSuggestion()
        assertEquals(listOf(listOf(first.task, second.task)), nextProvider.requests.map { it.completedTasks })
        assertEquals(2L, count("SELECT COUNT(*) FROM completion"))
    }

    // 저장 실패: iOS testGoalConfirmationFailureKeepsReviewAndInputAndCanRetry
    @Test
    fun testGoalConfirmationFailureKeepsReviewAndInputAndCanRetry() = runBlocking {
        val provider = ScriptedProvider(GoalSummary("메모를 정리했다"), Action(first))
        val flow = makeFlow(provider, preparing = false)
        val input = GoalInput(statement = "메모 정리", materialExcerpt = "선택한 한 줄")
        flow.prepareGoal(input)
        flow.awaitSuggestion()
        val before = flow.state.value
        probe.execSQL(
            "CREATE TRIGGER fail_goal_confirmation BEFORE INSERT ON suggestion_request WHEN NEW.kind = 'first_action' " +
                "BEGIN SELECT RAISE(ABORT, 'test failure'); END",
        )
        assertTrue(failure { flow.confirmGoal("사용자가 확인한 조건") } is SQLiteException)
        assertEquals(before, flow.state.value)
        val reopened = makeFlow(UnavailableSuggestionProvider, preparing = false)
        assertEquals(before.screen, reopened.state.value.screen)
        assertEquals(input, reopened.state.value.goalInput)

        probe.execSQL("DROP TRIGGER fail_goal_confirmation")
        flow.confirmGoal("사용자가 확인한 조건")
        flow.awaitSuggestion()
        assertEquals("사용자가 확인한 조건", flow.state.value.goal?.completionCriteria)
        assertEquals(GoalInput(), flow.state.value.goalInput)
        assertEquals(first.task, flow.card().task)
    }

    // '완료' 연타와 동시 호출. iOS testGoalToFirstActionToCompletionToNextActionSurvivesReopen의 연속 완료를 넓힌다.
    @Test
    fun testRepeatedAndConcurrentCompletionLeavesOneRecord() = runBlocking {
        val provider = ScriptedProvider(Action(first), Action(second), gated = true)
        val flow = makeFlow(provider)
        startGoal(flow, "방 한 칸 정리하기")
        provider.release()
        flow.awaitSuggestion()
        val firstCard = flow.card()

        coroutineScope { repeat(20) { launch(Dispatchers.Default) { flow.complete(firstCard.id) } } }
        assertEquals(ProgressScreen.AwaitingNextAction(null), flow.state.value.screen)
        assertEquals(1L, count("SELECT COUNT(*) FROM completion"))
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE kind = 'next_action'"))

        provider.release()
        flow.awaitSuggestion()
        // 이미 완료한 행동에 대한 늦은 호출은 새 현재 행동을 완료하지 않는다.
        flow.complete(firstCard.id)
        assertEquals(second.task, flow.card().task)
        assertEquals(1L, count("SELECT COUNT(*) FROM completion"))
    }

    // iOS testUnsavedSuggestionResultShowsFailureAndCanBeRetried. iOS는 DB 잠금으로, 여기서는 트리거로 결과 저장을 막는다.
    @Test
    fun testUnsavedSuggestionResultShowsFailureAndCanBeRetried() = runBlocking {
        probe.execSQL("CREATE TRIGGER fail_action BEFORE INSERT ON action BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        val flow = makeFlow(ScriptedProvider(Action(first), Action(first)))
        startGoal(flow, "주간 업무 보고서 초안 쓰기")
        flow.awaitSuggestion()
        val failed = ProgressScreen.AwaitingFirstAction("주간 업무 보고서 초안 쓰기", SuggestionProblem.Failure(SuggestionFailure.FAILED))
        assertEquals(failed, flow.state.value.screen)
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'pending'"))

        probe.execSQL("DROP TRIGGER fail_action")
        flow.retrySuggestion()
        flow.awaitSuggestion()
        assertEquals(first.task, flow.card().task)
        assertEquals(0L, count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'pending'"))
    }

    // 공급자가 자기 취소가 아닌 취소 예외(내부 시간 제한 등)를 던져도 요청이 pending으로 남지 않는다.
    @Test
    fun testProviderCancellationExceptionEndsRequestAsFailure() = runBlocking {
        val flow = makeFlow(ActionSuggestionProvider { kotlinx.coroutines.withTimeout(1) { kotlinx.coroutines.awaitCancellation() } })
        startGoal(flow, "방 한 칸 정리하기")
        flow.awaitSuggestion()
        val failed = ProgressScreen.AwaitingFirstAction("방 한 칸 정리하기", SuggestionProblem.Failure(SuggestionFailure.FAILED))
        assertEquals(failed, flow.state.value.screen)
        assertEquals(0L, count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'pending'"))
    }

    @Test
    fun testDelayedResultIsAppliedAndRetryWhileWaitingIsIgnored() = runBlocking {
        val provider = HeldProvider(Action(first))
        val flow = makeFlow(provider)
        startGoal(flow, "통계 강의 1장 끝내기")
        assertEquals(ProgressScreen.AwaitingFirstAction("통계 강의 1장 끝내기", null), flow.state.value.screen)

        flow.retrySuggestion()
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE kind != 'goal_preparation'"))

        provider.release()
        flow.awaitSuggestion()
        assertEquals(first.task, flow.card().task)
        assertEquals(1, provider.requests.get())
    }

    @Test
    fun testResultForChangedRevisionIsNotApplied() = runBlocking {
        val provider = HeldProvider(Action(first))
        val flow = makeFlow(provider)
        startGoal(flow, "방 한 칸 정리하기")
        probe.execSQL("UPDATE goal SET revision = revision + 1")
        provider.release()
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.AwaitingFirstAction("방 한 칸 정리하기", SuggestionProblem.Interrupted), flow.state.value.screen)
        assertEquals(0L, count("SELECT COUNT(*) FROM action"))
    }

    // 같은 목표에 pending 요청은 하나다. 다른 종류의 대기 요청은 완료를 막지 않고 끝난다.
    @Test
    fun testCompletionWhileAnotherSuggestionIsPendingSucceeds() = runBlocking {
        val provider = ScriptedProvider(Action(first), Action(second), gated = true)
        val flow = makeFlow(provider)
        startGoal(flow, "주간 업무 보고서 초안 쓰기")
        provider.release()
        flow.awaitSuggestion()
        probe.execSQL(
            "INSERT INTO suggestion_request (goal_id, kind, goal_revision, status, created_at) " +
                "SELECT id, 'smaller', revision, 'pending', 0 FROM goal",
        )

        flow.complete(flow.card().id)
        assertEquals(ProgressScreen.AwaitingNextAction(null), flow.state.value.screen)
        provider.release()
        flow.awaitSuggestion()
        assertEquals(second.task, flow.card().task)
        assertEquals(1L, count("SELECT COUNT(*) FROM completion"))
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE kind = 'smaller' AND status = 'interrupted'"))
    }

    // 행동 결과·입력 초안·카드 상세(#351). 이름은 iOS `ProgressFlowTests`와 같다.

    @Test
    fun testDraftAutosavesAndSurvivesReopenWithoutBecomingResult() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first)))
        val card = firstCard(flow)
        flow.updateDraft("첫 문장\n작성 중", card.id)
        flow.updateDraft("고친 문장\n작성 중", card.id)

        val restored = makeFlow(UnavailableSuggestionProvider).card()
        assertEquals("고친 문장\n작성 중", restored.draft)
        assertTrue(restored.results.isEmpty())
        assertEquals(card.id, restored.id)
        assertEquals(1L, count("SELECT COUNT(*) FROM action_note"))
        assertEquals(0L, count("SELECT COUNT(*) FROM completion"))
    }

    @Test
    fun testCardRestoresTargetLinksAndEarlierResultsForSameTarget() = runBlocking {
        val initial = first.copy(targetName = "업무 보고서")
        val other = second.copy(targetName = "다른 문서")
        val next = third.copy(
            targetName = "업무 보고서",
            targetDescription = "이번 주 업무를 적은 문서",
            materialLinks = listOf("https://example.com/report"),
        )
        val flow = makeFlow(ScriptedProvider(Action(initial), Action(other), Action(next)))
        val firstCard = firstCard(flow)
        flow.recordResult("확인한 기간: 10월 첫째 주", firstCard.id)
        flow.updateDraft("이 초안은 앞선 결과가 아니다", firstCard.id)
        flow.complete(firstCard.id)
        flow.awaitSuggestion()
        val secondCard = flow.card()
        flow.recordResult("다른 문서의 결과", secondCard.id)
        flow.complete(secondCard.id)
        flow.awaitSuggestion()

        val restored = makeFlow(UnavailableSuggestionProvider).card()
        assertEquals("업무 보고서", restored.targetName)
        assertEquals("이번 주 업무를 적은 문서", restored.targetDescription)
        assertEquals(listOf("https://example.com/report"), restored.materialLinks)
        assertEquals(listOf("확인한 기간: 10월 첫째 주"), restored.previousResults.map { it.body })
        assertTrue(restored.results.isEmpty())
        assertEquals("", restored.draft)
    }

    @Test
    fun testFailedResultCommitKeepsDraftAndScreenAndCanRetry() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first)))
        val card = firstCard(flow)
        flow.updateDraft("지우면 안 되는 초안", card.id)
        val before = flow.state.value.screen
        probe.execSQL("CREATE TRIGGER reject_draft_delete BEFORE DELETE ON action_note BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        assertTrue(failure { flow.recordResult("지우면 안 되는 초안", card.id) } is SQLiteException)
        assertEquals(before, flow.state.value.screen)
        assertEquals(before, makeFlow(UnavailableSuggestionProvider).state.value.screen)

        probe.execSQL("DROP TRIGGER reject_draft_delete")
        flow.recordResult("지우면 안 되는 초안", card.id)
        val saved = flow.card()
        assertEquals(listOf("지우면 안 되는 초안"), saved.results.map { it.body })
        assertEquals("", saved.draft)
    }

    // 사라지는 카드에 늦게 들어온 입력이 새 카드나 DB에 섞이지 않는다.
    @Test
    fun testStaleActionCannotSaveDraftIntoAnotherCard() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first), Action(second)))
        val old = firstCard(flow)
        flow.complete(old.id)
        flow.awaitSuggestion()
        val current = flow.state.value.screen
        val stale = failure { flow.updateDraft("늦은 입력", old.id) }
        assertEquals(ProgressFlowException.Reason.ACTION_NOT_CURRENT, (stale as ProgressFlowException).reason)
        assertTrue(failure { flow.recordResult("늦은 결과", old.id) } is ProgressFlowException)
        assertEquals(current, flow.state.value.screen)
        assertEquals(current, makeFlow(UnavailableSuggestionProvider).state.value.screen)
        assertEquals(0L, count("SELECT COUNT(*) FROM action_note"))
    }

    @Test
    fun testSameTargetNameInDifferentGoalDoesNotShareResults() = runBlocking {
        val proposed = first.copy(targetName = "같은 이름의 자료")
        val flow = makeFlow(ScriptedProvider(Action(proposed)))
        val card = firstCard(flow)
        flow.recordResult("이 목표에만 남긴 결과", card.id)

        val other = newGoalFlow(ScriptedProvider(Action(proposed)))
        startGoal(other, "다른 목표")
        other.awaitSuggestion()
        val current = other.card()
        assertEquals("같은 이름의 자료", current.targetName)
        assertTrue(current.previousResults.isEmpty())
        assertTrue(current.results.isEmpty())
        assertEquals("", current.draft)
    }

    // iOS testDraftSaveAfterUnsavedSuggestionResultKeepsRetryAvailable은 '더 작게' 대기 중에 카드가 남는 경로다.
    // Android에는 아직 '더 작게'가 없어 #353에서 옮긴다. 초안 저장도 다른 명령처럼 `perform`을 거쳐 실패 상태를 함께 저장한다.

    @Test
    fun testBlankResultIsNotRecorded() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first)))
        val card = firstCard(flow)
        flow.updateDraft(" \n ", card.id)
        val error = failure { flow.recordResult(" \n ", card.id) }
        assertEquals(ProgressFlowException.Reason.EMPTY_RESULT, (error as ProgressFlowException).reason)
        assertEquals(" \n ", flow.card().draft)
        assertEquals(0L, count("SELECT COUNT(*) FROM action_note WHERE NOT is_draft"))
    }

    @Test
    fun testFirstActionFailureKeepsGoalWithoutAutomaticRetry() = runBlocking {
        val all = SuggestionFailure.entries
        val provider = ScriptedProvider(failures(*all.toTypedArray()))
        for (failure in all) {
            val goal = "목표 ${failure.raw}"
            val flow = newGoalFlow(provider)
            startGoal(flow, goal)
            flow.awaitSuggestion()
            assertEquals(ProgressScreen.AwaitingFirstAction(goal, SuggestionProblem.Failure(failure)), flow.state.value.screen)
            assertEquals(goal, flow.state.value.goal?.statement)
        }
        delay(50)
        assertEquals(all.size, provider.requests.size)
        assertEquals(0L, count("SELECT COUNT(*) FROM action"))
    }

    @Test
    fun testNextActionFailureKeepsCompletionOffline() = runBlocking {
        val all = SuggestionFailure.entries
        val provider = ScriptedProvider(all.flatMap { listOf(Result.success(Action(first))) + failures(it) }, gated = true)
        for (failure in all) {
            val flow = newGoalFlow(provider)
            startGoal(flow, "목표 ${failure.raw}")
            provider.release()
            flow.awaitSuggestion()
            flow.complete(flow.card().id)
            assertEquals(ProgressScreen.AwaitingNextAction(null), flow.state.value.screen)
            provider.release()
            flow.awaitSuggestion()
            assertEquals(ProgressScreen.AwaitingNextAction(SuggestionProblem.Failure(failure)), flow.state.value.screen)
        }
        delay(50)
        assertEquals(all.size * 2, provider.requests.size)

        val reopened = makeFlow(ScriptedProvider())
        assertEquals(ProgressScreen.AwaitingNextAction(SuggestionProblem.Failure(all.last())), reopened.state.value.screen)
        assertEquals(all.size.toLong(), count("SELECT COUNT(*) FROM completion"))
    }

    @Test
    fun testCancelReachesProviderAndKeepsGoal() = runBlocking {
        val provider = SuspendedProvider()
        val flow = makeFlow(provider)
        startGoal(flow, "통계 강의 1장 끝내기")
        awaitRequest(provider.requests)
        flow.cancelSuggestion()
        val cancelled = ProgressScreen.AwaitingFirstAction("통계 강의 1장 끝내기", SuggestionProblem.Cancelled)
        assertEquals(cancelled, flow.state.value.screen)
        flow.awaitSuggestion()
        assertTrue(provider.cancelled)
        assertEquals(cancelled, flow.state.value.screen)
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'cancelled'"))
        // 취소한 뒤의 취소는 무시한다. 다시 시도는 같은 종류로 한 번만 요청한다.
        flow.cancelSuggestion()
        flow.retrySuggestion()
        assertEquals(ProgressScreen.AwaitingFirstAction("통계 강의 1장 끝내기", null), flow.state.value.screen)
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'cancelled'"))
        withTimeout(5_000) { while (provider.requests.get() < 2) delay(10) }
    }

    @Test
    fun testResultArrivingAfterCancelIsNotApplied() = runBlocking {
        val provider = HeldProvider(Action(first))
        val flow = makeFlow(provider)
        startGoal(flow, "방 한 칸 정리하기")
        awaitRequest(provider.requests)
        flow.cancelSuggestion()
        provider.release()
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.AwaitingFirstAction("방 한 칸 정리하기", SuggestionProblem.Cancelled), flow.state.value.screen)
        assertEquals(0L, count("SELECT COUNT(*) FROM action"))
    }

    @Test
    fun testPendingSuggestionIsInterruptedAfterReopenAndCanBeRetried() = runBlocking {
        val waiting = makeFlow(SuspendedProvider())
        startGoal(waiting, "통계 강의 1장 끝내기")
        assertEquals(ProgressScreen.AwaitingFirstAction("통계 강의 1장 끝내기", null), waiting.state.value.screen)
        closeAll()

        val provider = ScriptedProvider(Action(first))
        val reopened = makeFlow(provider)
        assertEquals(ProgressScreen.AwaitingFirstAction("통계 강의 1장 끝내기", SuggestionProblem.Interrupted), reopened.state.value.screen)
        assertTrue(provider.requests.isEmpty())

        reopened.retrySuggestion()
        reopened.awaitSuggestion()
        assertEquals(first.task, reopened.card().task)
        assertEquals(listOf(SuggestionKind.FIRST_ACTION), provider.requests.map { it.kind })
    }

    @Test
    fun testPendingNextActionIsInterruptedAfterReopenAndKeepsCompletion() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first)))
        startGoal(flow, "주간 업무 보고서 초안 쓰기")
        flow.awaitSuggestion()
        closeAll()
        val waiting = makeFlow(SuspendedProvider())
        waiting.complete(waiting.card().id)
        assertEquals(ProgressScreen.AwaitingNextAction(null), waiting.state.value.screen)
        closeAll()

        val reopened = makeFlow(ScriptedProvider())
        assertEquals(ProgressScreen.AwaitingNextAction(SuggestionProblem.Interrupted), reopened.state.value.screen)
        assertEquals(1L, count("SELECT COUNT(*) FROM completion"))
    }

    @Test
    fun testGoalPreparationInterruptedOnReopenKeepsInputAndCanRetry() = runBlocking {
        val input = GoalInput(statement = "기초 단원 학습하기", availableMinutes = "10")
        val held = HeldProvider(GoalSummary("기초 개념을 설명할 수 있다"))
        val flow = makeFlow(held, preparing = false)
        flow.prepareGoal(input)
        assertTrue(flow.state.value.screen.isWaitingForSuggestion)
        assertTrue(failure { flow.confirmGoal("아직 확인하지 않았다") } is ProgressFlowException)
        val provider = ScriptedProvider(GoalSummary("학습한 내용을 설명할 수 있다"))
        val reopened = makeFlow(provider, preparing = false)
        assertEquals(input, reopened.state.value.goalInput)
        assertEquals(ProgressScreen.PreparingGoal(null, null, SuggestionProblem.Interrupted), reopened.state.value.screen)
        assertTrue(provider.requests.isEmpty())

        held.release()
        flow.awaitSuggestion()
        assertEquals(reopened.state.value.screen, flow.state.value.screen)
        reopened.retrySuggestion()
        reopened.awaitSuggestion()
        assertEquals(ProgressScreen.PreparingGoal(null, "학습한 내용을 설명할 수 있다", null), reopened.state.value.screen)
        assertNull(reopened.state.value.goal?.context?.currentState)
        assertNull(reopened.state.value.goal?.completionCriteria)
    }

    // JVM CandidatePolicyTest의 같은 이름 테스트가 규칙을, 이 테스트는 요청의 완료 목록이 채워지는 실제 경로를 확인한다.
    @Test
    fun testRepeatedCompletedActionIsNotApplied() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first), Action(first.copy(task = "  ${first.task}\n"))))
        startGoal(flow, "방 한 칸 정리하기")
        flow.awaitSuggestion()
        flow.complete(flow.card().id)
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.AwaitingNextAction(SuggestionProblem.Unsuitable), flow.state.value.screen)
    }

    // 더 작게(#353). 이름은 iOS ProgressFlowTests와 같다.

    @Test
    fun testSmallerThenCompleteKeepsSplitSourceAndGoalOpen() = runBlocking {
        val provider = ScriptedProvider(Action(first), SuggestionCandidate.MinimalAction(smaller), Action(second), gated = true)
        val flow = makeFlow(provider)
        startGoal(flow, "주간 업무 보고서 초안 쓰기")
        provider.release()
        flow.awaitSuggestion()
        val source = flow.card()
        probe.execSQL("UPDATE goal SET blocker = '시간이 부족함', completion_criteria = '초안 한 쪽'")

        flow.makeSmaller()
        // 질문 없이 바로 요청한다.
        assertEquals(current(source, SmallerStatus.Waiting), flow.state.value.screen)
        provider.release()
        flow.awaitSuggestion()
        val small = flow.card()
        assertNull(flow.smaller())
        assertEquals(smaller.task, small.task)
        assertEquals(ActionCard.Origin(source.id, first.task), small.origin)
        assertEquals("split", status(first.task))

        flow.complete(small.id)
        provider.release()
        flow.awaitSuggestion()
        assertEquals("done", status(smaller.task))
        assertEquals("split", status(first.task))
        assertEquals(1L, count("SELECT COUNT(*) FROM completion"))
        assertEquals(1L, count("SELECT COUNT(*) FROM goal WHERE status = 'active' AND completion_criteria = '초안 한 쪽'"))

        val requests = provider.requests
        assertEquals(listOf(SuggestionKind.FIRST_ACTION, SuggestionKind.SMALLER, SuggestionKind.NEXT_ACTION), requests.map { it.kind })
        assertEquals(card(first), requests[1].currentAction)
        assertEquals("시간이 부족함", requests[1].blocker)
        // 작은 행동을 완료한 뒤에도 분할 원본의 남은 범위를 다음 요청에 전달한다.
        assertEquals(card(first), requests[2].currentAction)
        assertEquals(listOf(smaller.task), requests[2].completedTasks)
    }

    @Test
    fun testSmallerThenUndoRestoresSourceAndKeepsResults() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first), Action(smaller)))
        val source = firstCard(flow)
        flow.makeSmaller()
        flow.awaitSuggestion()
        val small = flow.card()
        probe.execSQL("INSERT INTO action_note (action_id, body, is_draft, updated_at) VALUES (${small.id}, '제목: 주간 보고', 0, 0)")

        flow.undoSplit()
        assertEquals(current(source), flow.state.value.screen)
        assertEquals("deferred", status(smaller.task))
        assertEquals(1L, count("SELECT COUNT(*) FROM action_note"))
        assertEquals(0L, count("SELECT COUNT(*) FROM completion"))

        // 분할 원본은 되돌릴 대상이 없다.
        flow.undoSplit()
        assertEquals(current(source), flow.state.value.screen)

        closeAll()
        assertEquals(current(source), makeFlow(ScriptedProvider()).state.value.screen)
    }

    @Test
    fun testRepeatedSmallerSendsSplitSourcesAndUndoesOneStep() = runBlocking {
        val smallest = ProposedAction("메모 앱 열기", "메모 앱이 열려 있다", 1)
        val provider = ScriptedProvider(Action(first), Action(smaller), Action(smallest))
        val flow = makeFlow(provider)
        firstCard(flow)
        flow.makeSmaller()
        flow.awaitSuggestion()
        val small = flow.card()
        flow.makeSmaller()
        flow.awaitSuggestion()
        assertEquals(ActionCard.Origin(small.id, smaller.task), flow.card().origin)

        // 공급자가 같은 행동을 이미 나눴는지 알 수 있게 분할 원본을 처음 것부터 담는다.
        assertEquals(emptyList<String>(), provider.requests[1].splitSources)
        assertEquals(card(smaller), provider.requests[2].currentAction)
        assertEquals(listOf(first.task), provider.requests[2].splitSources)

        flow.undoSplit()
        assertEquals(current(small), flow.state.value.screen)
    }

    @Test
    fun testQuestionAnswerIsSavedAsBlockerAndSentWithNextRequest() = runBlocking {
        val provider = ScriptedProvider(Action(first), Question(question), Action(smaller))
        val flow = makeFlow(provider)
        val source = firstCard(flow)

        flow.makeSmaller()
        flow.awaitSuggestion()
        assertEquals(current(source, SmallerStatus.Question(question)), flow.state.value.screen)
        assertEquals("current", status(first.task))
        val requestId = flow.state.value.suggestionInput!!.requestId
        flow.updateSuggestionInput(" 어떤 자료를 봐야 할지 모름 ", requestId)

        closeAll()
        val reopened = makeFlow(provider)
        assertEquals(current(source, SmallerStatus.Question(question)), reopened.state.value.screen)
        assertEquals(" 어떤 자료를 봐야 할지 모름 ", reopened.state.value.suggestionInput?.text)
        assertEquals(ProgressFlowException.Reason.EMPTY_ANSWER, (failure { reopened.answerQuestion("  ") } as ProgressFlowException).reason)
        reopened.answerQuestion(" 어떤 자료를 봐야 할지 모름 ")
        assertEquals(SmallerStatus.Waiting, reopened.smaller())
        assertNull(reopened.state.value.suggestionInput)
        reopened.awaitSuggestion()
        assertEquals(smaller.task, reopened.card().task)
        assertEquals(1L, count("SELECT COUNT(*) FROM goal WHERE blocker = '어떤 자료를 봐야 할지 모름'"))

        assertEquals(listOf(SuggestionKind.FIRST_ACTION, SuggestionKind.SMALLER, SuggestionKind.SMALLER), provider.requests.map { it.kind })
        assertNull(provider.requests[1].blocker)
        assertEquals("어떤 자료를 봐야 할지 모름", provider.requests[2].blocker)
    }

    @Test
    fun testUndoWhileWaitingEndsRequestAndSmallerCanStartAgain() = runBlocking {
        val setup = makeFlow(ScriptedProvider(Action(first), Action(smaller)))
        firstCard(setup)
        setup.makeSmaller()
        setup.awaitSuggestion()
        closeAll()
        val held = HeldProvider(Action(smaller))
        val flow = makeFlow(held)
        val origin = flow.card().origin!!
        flow.makeSmaller()
        awaitRequest(held.requests)
        flow.undoSplit()
        val source = flow.card()
        assertEquals(origin.id, source.id)
        held.release()
        flow.awaitSuggestion()
        // 되돌린 뒤 도착한 결과는 적용하지 않는다.
        assertEquals(current(source), flow.state.value.screen)
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'interrupted'"))

        // HeldProvider는 한 번만 풀린다. 다시 나누는 요청은 결과를 따로 붙잡는 공급자로 다시 연다.
        closeAll()
        val provider = ScriptedProvider(Action(smaller), gated = true)
        val again = makeFlow(provider)
        again.makeSmaller()
        assertEquals(current(source, SmallerStatus.Waiting), again.state.value.screen)
        provider.release()
        again.awaitSuggestion()
        assertEquals(source.id, again.card().origin?.id)
    }

    @Test
    fun testAnsweredQuestionIsNotAskedAgain() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first), Question(question), Question(" $question")))
        val source = firstCard(flow)
        flow.makeSmaller()
        flow.awaitSuggestion()
        flow.answerQuestion("자료 위치를 모름")
        flow.awaitSuggestion()
        assertEquals(current(source, SmallerStatus.Problem(SuggestionProblem.Unsuitable)), flow.state.value.screen)
    }

    @Test
    fun testUnansweredQuestionCanBeAskedAgain() = runBlocking {
        val skipped = "어떤 자료가 먼저 필요한가요?"
        val flow = makeFlow(
            ScriptedProvider(Action(first), Question(question), Action(smaller), Action(second), Question(skipped), Action(third), Question(skipped)),
        )
        firstCard(flow)
        flow.makeSmaller()
        flow.awaitSuggestion()
        flow.answerQuestion("자료 위치를 모름")
        flow.awaitSuggestion()
        flow.complete(flow.card().id)
        flow.awaitSuggestion()
        flow.makeSmaller()
        flow.awaitSuggestion()
        assertEquals(SmallerStatus.Question(skipped), flow.smaller())
        // 질문에 답하지 않고 완료한다. 같은 질문을 다시 받으면 보여준다.
        flow.complete(flow.card().id)
        flow.awaitSuggestion()
        flow.makeSmaller()
        flow.awaitSuggestion()
        assertEquals(SmallerStatus.Question(skipped), flow.smaller())
        assertEquals(third.task, flow.card().task)
    }

    @Test
    fun testUndoWhileWaitingCancelsProvider() = runBlocking {
        val setup = makeFlow(ScriptedProvider(Action(first), Action(smaller)))
        firstCard(setup)
        setup.makeSmaller()
        setup.awaitSuggestion()
        closeAll()
        val provider = SuspendedProvider()
        val flow = makeFlow(provider)
        flow.makeSmaller()
        awaitRequest(provider.requests)
        flow.undoSplit()
        flow.awaitSuggestion()
        assertTrue(provider.cancelled)
    }

    // iOS는 DB 잠금으로, 여기서는 트리거로 결과 저장을 막는다.
    @Test
    fun testUnsavedSmallerResultCanBeRetried() = runBlocking {
        val flow = makeFlow(ScriptedProvider(Action(first), Action(smaller), Action(smaller)))
        val source = firstCard(flow)
        probe.execSQL("CREATE TRIGGER fail_action BEFORE INSERT ON action BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        flow.makeSmaller()
        flow.awaitSuggestion()
        assertEquals(current(source, SmallerStatus.Problem(SuggestionProblem.Failure(SuggestionFailure.FAILED))), flow.state.value.screen)

        probe.execSQL("DROP TRIGGER fail_action")
        flow.makeSmaller()
        flow.awaitSuggestion()
        assertEquals(smaller.task, flow.card().task)
        assertEquals(0L, count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'pending'"))
    }

    @Test
    fun testSmallerFailureAndCancelKeepCurrentAction() = runBlocking {
        val provider = ScriptedProvider(
            listOf(Result.success(Action(first))) + failures(SuggestionFailure.TIMED_OUT) + Result.success(Question(" ")),
        )
        val flow = makeFlow(provider)
        val source = firstCard(flow)

        flow.makeSmaller()
        flow.awaitSuggestion()
        assertEquals(current(source, SmallerStatus.Problem(SuggestionProblem.Failure(SuggestionFailure.TIMED_OUT))), flow.state.value.screen)
        flow.makeSmaller()
        flow.awaitSuggestion()
        assertEquals(current(source, SmallerStatus.Problem(SuggestionProblem.Unsuitable)), flow.state.value.screen)

        closeAll()
        val waiting = makeFlow(SuspendedProvider())
        waiting.makeSmaller()
        waiting.makeSmaller()
        assertEquals(1L, count("SELECT COUNT(*) FROM suggestion_request WHERE status = 'pending'"))
        waiting.cancelSuggestion()
        assertEquals(current(source, SmallerStatus.Problem(SuggestionProblem.Cancelled)), waiting.state.value.screen)
        assertEquals("current", status(first.task))
    }

    @Test
    fun testRemainingSplitWorkSurvivesTwoNextActionsAndReopen() = runBlocking {
        val fourth = ProposedAction("자료 저장하기", "자료가 저장됐다", 1)
        val fifth = ProposedAction("자료 위치 확인하기", "위치를 확인했다", 1)
        val provider = ScriptedProvider(Action(first), Action(second), Action(third), Action(fourth), Action(fifth))
        val flow = makeFlow(provider)
        startGoal(flow, "학습 자료 정리")
        flow.awaitSuggestion()
        flow.makeSmaller()
        flow.awaitSuggestion()
        flow.complete(flow.card().id)
        flow.awaitSuggestion()
        flow.complete(flow.card().id)
        flow.awaitSuggestion()
        assertTrue(first.task in provider.requests.last().remainingTasks)
        assertEquals(2, provider.requests.last().completedActionIds.size)
        assertFalse(provider.requests.last().stateKey.isEmpty())

        closeAll()
        val reopened = makeFlow(provider)
        reopened.complete(reopened.card().id)
        reopened.awaitSuggestion()
        assertTrue(first.task in provider.requests.last().remainingTasks)
        assertEquals(3, provider.requests.last().completedActionIds.size)
    }

    // iOS testSplitInheritsTargetAndNotesSurviveUndoAndResume의 분할·되돌리기 부분이다. 보류·재개는 #354에서 더한다.
    @Test
    fun testSplitInheritsTargetAndNotesSurviveUndoAndResume() = runBlocking {
        val initial = first.copy(targetName = "업무 보고서", targetDescription = "내가 작성 중인 보고서", materialLinks = listOf("https://example.com/report"))
        val flow = makeFlow(ScriptedProvider(Action(initial), Action(smaller)))
        val source = firstCard(flow)
        flow.recordResult("원본에 남긴 결과", source.id)
        flow.updateDraft("원본 초안", source.id)
        flow.makeSmaller()
        flow.awaitSuggestion()
        val small = flow.card()
        assertEquals(initial.targetName, small.targetName)
        assertEquals(initial.targetDescription, small.targetDescription)
        assertEquals(initial.materialLinks, small.materialLinks)
        assertEquals(listOf("원본에 남긴 결과"), small.previousResults.map { it.body })
        flow.recordResult("작은 행동의 결과", small.id)
        flow.updateDraft("작은 행동 초안", small.id)
        flow.undoSplit()

        closeAll()
        val restored = makeFlow(UnavailableSuggestionProvider).card()
        assertEquals("원본 초안", restored.draft)
        assertEquals(listOf("원본에 남긴 결과"), restored.results.map { it.body })
        assertEquals(listOf("작은 행동의 결과"), restored.previousResults.map { it.body })
    }

    // 화면이 누른 카드의 ID를 넘기면 그사이 바뀐 현재 행동에는 더 작게·되돌리기를 실행하지 않는다.
    @Test
    fun testSmallerAndUndoIgnoreAStaleCard() = runBlocking {
        val smallest = ProposedAction("메모 앱 열기", "메모 앱이 열려 있다", 1)
        val provider = ScriptedProvider(Action(first), Action(smaller), Action(smallest))
        val flow = makeFlow(provider)
        val source = firstCard(flow)
        flow.makeSmaller(source.id)
        flow.awaitSuggestion()
        val small = flow.card()
        flow.makeSmaller(source.id)
        assertEquals(current(small), flow.state.value.screen)
        flow.makeSmaller(small.id)
        flow.awaitSuggestion()
        val tiny = flow.card()
        // 작은 행동 카드에서 누른 되돌리기가 더 작은 행동에 닿지 않는다.
        flow.undoSplit(small.id)
        assertEquals(current(tiny), flow.state.value.screen)
        flow.undoSplit(tiny.id)
        assertEquals(current(small), flow.state.value.screen)
        assertEquals(3, provider.requests.size)
    }
}

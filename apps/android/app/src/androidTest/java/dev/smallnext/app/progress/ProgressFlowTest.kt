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
    private val probe by lazy { open().openHelper.writableDatabase }

    private val first = ProposedAction("관련 메모 하나 열기", "메모가 화면에 열려 있다", 3)
    private val second = ProposedAction("첫 문단 한 줄 쓰기", "문장 한 줄이 저장돼 있다", 5)
    private val third = ProposedAction("제목 한 줄 정하기", "제목이 적혀 있다", 2)

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

    private fun count(sql: String) = probe.query(sql).use { it.moveToFirst(); it.getLong(0) }

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
}

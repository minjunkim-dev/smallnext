package dev.smallnext.app.progress

import android.database.sqlite.SQLiteException
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
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
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

    private suspend fun firstCard(flow: ProgressFlow): ActionCard {
        startGoal(flow, "주간 업무 보고서 초안 쓰기")
        flow.awaitSuggestion()
        return flow.card()
    }

    private fun count(sql: String) = probe.query(sql).use { it.moveToFirst(); it.getLong(0) }

    private suspend fun failure(command: suspend () -> Unit) = runCatching { command() }.exceptionOrNull()

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

    // 새 목표 시작 명령은 여러 목표 티켓에서 더한다. 여기서는 선택한 목표를 지워 목표 입력으로 돌아간다.
    @Test
    fun testSameTargetNameInDifferentGoalDoesNotShareResults() = runBlocking {
        val proposed = first.copy(targetName = "같은 이름의 자료")
        val flow = makeFlow(ScriptedProvider(Action(proposed)))
        val card = firstCard(flow)
        flow.recordResult("이 목표에만 남긴 결과", card.id)
        probe.execSQL("DELETE FROM app_metadata WHERE `key` = 'selected_goal_id'")

        val other = makeFlow(ScriptedProvider(Action(proposed)))
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
}

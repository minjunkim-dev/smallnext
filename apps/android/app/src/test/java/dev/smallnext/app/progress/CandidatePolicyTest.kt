package dev.smallnext.app.progress

import dev.smallnext.app.progress.SuggestionCandidate.Action
import dev.smallnext.app.progress.SuggestionCandidate.GoalSummary
import dev.smallnext.app.progress.SuggestionCandidate.InsufficientInfo
import dev.smallnext.app.progress.SuggestionCandidate.MinimalAction
import dev.smallnext.app.progress.SuggestionCandidate.NoAction
import dev.smallnext.app.progress.SuggestionCandidate.Question
import dev.smallnext.app.progress.SuggestionKind.FIRST_ACTION
import dev.smallnext.app.progress.SuggestionKind.GOAL_PREPARATION
import dev.smallnext.app.progress.SuggestionKind.NEXT_ACTION
import dev.smallnext.app.progress.SuggestionKind.REPLACEMENT
import dev.smallnext.app.progress.SuggestionKind.SMALLER
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/** iOS `CandidatePolicyTests`와 같은 이름·기대 결과다. */
class CandidatePolicyTest {
    private val action = ProposedAction("관련 메모 하나 열기", "메모가 화면에 열려 있다", 3)

    private fun request(kind: SuggestionKind) =
        SuggestionRequest(kind, "자료 정리", currentAction = action, deferredTasks = listOf("보류한 일"))

    @Test
    fun testCandidateTypeMustMatchRequestKind() {
        val all = SuggestionKind.entries.toSet()
        val actionKinds = setOf(FIRST_ACTION, NEXT_ACTION, SMALLER, REPLACEMENT)
        val cases = listOf(
            GoalSummary("메모가 정리돼 있다") to setOf(GOAL_PREPARATION),
            NoAction to setOf(REPLACEMENT),
            Question("어느 메모인가요?") to all,
            InsufficientInfo("지금은 근거가 부족해요") to actionKinds,
            Action(ProposedAction("새 일", "끝남", 1)) to actionKinds,
            MinimalAction(ProposedAction("새 일", "끝남", 1)) to actionKinds,
        )
        for ((candidate, accepted) in cases) {
            for (kind in all) {
                assertEquals("$candidate $kind", kind in accepted, CandidatePolicy.accept(candidate, request(kind)) != null)
            }
        }
    }

    @Test
    fun testIncompleteOrClaimingActionsAreRejectedAndTextIsTrimmed() {
        val invalid = listOf(
            action.copy(task = " \n"),
            action.copy(doneWhen = ""),
            action.copy(estimatedMinutes = 0),
            action.copy(marksGoalComplete = true),
            action.copy(marksCurrentActionComplete = true),
            action.copy(materialLinks = listOf("file:///tmp/a")),
            action.copy(materialLinks = listOf("https://")),
        )
        for (candidate in invalid) assertNull("$candidate", CandidatePolicy.accept(Action(candidate), request(FIRST_ACTION)))
        assertNull(CandidatePolicy.accept(GoalSummary("  "), request(GOAL_PREPARATION)))
        assertNull(CandidatePolicy.accept(Question("\n"), request(SMALLER)))
        assertEquals(
            Action(ProposedAction("새 일", action.doneWhen, 3)),
            CandidatePolicy.accept(Action(action.copy(task = "  새 일\n", targetName = " ")), request(FIRST_ACTION)),
        )
        assertEquals(Question("어느 메모인가요?"), CandidatePolicy.accept(Question(" 어느 메모인가요? "), request(SMALLER)))
        assertNotNull(CandidatePolicy.accept(Action(action.copy(materialLinks = listOf("HTTPS://example.com/a"))), request(FIRST_ACTION)))
    }

    @Test
    fun testSmallerExcludesCurrentActionAndOthersExcludeDeferredActions() {
        val deferred = action.copy(task = " 보류한 일")
        assertNull(CandidatePolicy.accept(Action(action), request(SMALLER)))
        assertNotNull(CandidatePolicy.accept(Action(deferred), request(SMALLER)))
        for (kind in listOf(FIRST_ACTION, NEXT_ACTION, REPLACEMENT)) {
            assertNull("$kind", CandidatePolicy.accept(MinimalAction(deferred), request(kind)))
            assertNotNull("$kind", CandidatePolicy.accept(Action(action), request(kind)))
        }
    }
}

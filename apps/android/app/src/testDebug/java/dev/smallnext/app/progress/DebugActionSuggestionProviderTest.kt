package dev.smallnext.app.progress

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Debug 고정 공급자는 Debug 소스에만 있다. 이 테스트도 Debug 단위 테스트에서만 컴파일된다. */
class DebugActionSuggestionProviderTest {
    // iOS testDebugProviderFirstCandidateAndExampleGoals 대응
    @Test
    fun debugProviderFirstCandidateAndExampleGoals() = runBlocking {
        val goals = DebugActionSuggestionProvider.exampleGoals
        assertEquals(1, goals.count { "이력서" in it })
        assertTrue(goals.count { "이력서" !in it } >= 3)
        // 업무·학습·개인 예시 목표를 하나 이상 포함한다.
        listOf("업무", "학습", "개인").forEach { kind -> assertTrue(kind, goals.any { kind in it }) }

        val provider = DebugActionSuggestionProvider(delayMillis = 0)
        val first = provider.suggest(SuggestionRequest(SuggestionKind.FIRST_ACTION, goals[0])) as SuggestionCandidate.Action
        assertFalse(first.action.marksGoalComplete)
        assertTrue(first.action.estimatedMinutes in 2..15)
        // 진행 흐름의 후보 검사를 통과하는 행동이다.
        assertEquals(first, CandidatePolicy.accept(first, SuggestionRequest(SuggestionKind.FIRST_ACTION, goals[0])))

        val continued = provider.suggest(
            SuggestionRequest(SuggestionKind.NEXT_ACTION, goals[0], completedTasks = List(5) { "완료" }),
        ) as SuggestionCandidate.Action
        assertEquals("다음 한 가지 고르기 (5)", continued.action.task)
    }

    @Test
    fun goalPreparationAsksOnlyForAmbiguousGoalsWithoutContext() = runBlocking {
        val provider = DebugActionSuggestionProvider(delayMillis = 0)
        assertEquals(
            SuggestionCandidate.Question("무엇을 하려는지 한 가지 알려 주세요."),
            provider.suggest(SuggestionRequest(SuggestionKind.GOAL_PREPARATION, "정리하기")),
        )
        assertEquals(
            SuggestionCandidate.GoalSummary("‘이력서 정리하기’을 마쳤다고 확인한다."),
            provider.suggest(SuggestionRequest(SuggestionKind.GOAL_PREPARATION, "이력서 정리하기")),
        )
    }
}

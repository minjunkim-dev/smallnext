package dev.smallnext.app.progress

import java.net.URI

/**
 * 진행 흐름 모듈이 주입받는 행동 제안 공급자 경계다. iOS `ActionSuggestionProvider`와 같은 타입이다.
 * 구현은 자동 재시도를 하지 않는다. 취소는 코루틴 취소로 전달한다. 실패하면 [SuggestionException]을 던진다.
 */
fun interface ActionSuggestionProvider {
    suspend fun suggest(request: SuggestionRequest): SuggestionCandidate
}

enum class SuggestionKind(val raw: String) {
    GOAL_PREPARATION("goal_preparation"),
    FIRST_ACTION("first_action"),
    NEXT_ACTION("next_action"),
    SMALLER("smaller"),
    REPLACEMENT("replacement");

    companion object {
        fun of(raw: String?) = entries.firstOrNull { it.raw == raw }
    }
}

data class SuggestionRequest(
    val kind: SuggestionKind,
    val goal: String,
    val currentAction: ProposedAction? = null,
    /** 완료한 행동의 할 일. 오래된 것부터 담는다. */
    val completedTasks: List<String> = emptyList(),
    /** 사용자가 알려준 막힘 원인이다. 같은 정보를 다시 묻지 않게 한다. */
    val blocker: String? = null,
    /** 더 작게 요청에서 현재 행동을 나눈 분할 원본의 할 일. 가장 처음 원본부터 담는다. */
    val splitSources: List<String> = emptyList(),
    /** 보류한 행동의 할 일. 공급자는 이 행동을 다시 제안하지 않는다. */
    val deferredTasks: List<String> = emptyList(),
    val context: GoalContext = GoalContext(),
    val completionCriteria: String? = null,
    /** 같은 목표 리비전의 HTTP 중복 요청을 막는 키다. "목표 ID:리비전" */
    val stateKey: String = "",
    /** 완료한 행동과 구분하는 미완료 분할 원본·현재·보류 행동이다. */
    val remainingTasks: List<String> = emptyList(),
    val completedActionIds: List<String> = emptyList(),
    /** 행동 요청에 연결해 확인한 질문과 답이다. 목표 준비와 막힘 원인과 구분한다. */
    val actionAnswers: List<GoalAnswer> = emptyList(),
    /** 명시적으로 재요청할 때 전송하는 보충 입력 확인 저장값이다. */
    val supplementalText: String = "",
)

data class GoalAnswer(val question: String, val answer: String)

/** 자료 본문을 자동으로 읽지 않는다. 링크와 사용자가 고른 발췌·요약만 담는다. */
data class GoalContext(
    val deadline: String? = null,
    val currentState: String? = null,
    val materialLinks: List<String> = emptyList(),
    val materialExcerpt: String? = null,
    val availableMinutes: Int? = null,
    val answers: List<GoalAnswer> = emptyList(),
)

data class ProposedAction(
    val task: String,
    val doneWhen: String,
    val estimatedMinutes: Int,
    val targetName: String? = null,
    val targetDescription: String? = null,
    val materialLinks: List<String> = emptyList(),
    /** 앱은 이 표시로 목표를 완료하지 않는다. */
    val marksGoalComplete: Boolean = false,
    /** 앱은 이 표시로 원래 행동을 완료하지 않는다. */
    val marksCurrentActionComplete: Boolean = false,
)

sealed interface SuggestionCandidate {
    /** 사용자가 확인하기 전에는 목표의 완료 조건으로 저장하지 않는다. */
    data class GoalSummary(val criteria: String) : SuggestionCandidate
    data class Action(val action: ProposedAction) : SuggestionCandidate
    data class Question(val question: String) : SuggestionCandidate
    data class MinimalAction(val action: ProposedAction) : SuggestionCandidate
    /** 선행 조건이 준비된 다른 행동이 없다. 대체 요청에서만 쓴다. */
    data object NoAction : SuggestionCandidate
    /** 유용한 행동이나 실제 미답 질문을 제안할 근거가 부족한 정상 안내다. */
    data class InsufficientInfo(val reason: String) : SuggestionCandidate
}

enum class SuggestionFailure(val raw: String) {
    CONNECTION_LOST("connection_lost"),
    REJECTED("rejected"),
    UNDECIDABLE("undecidable"),
    FAILED("failed"),
    TIMED_OUT("timed_out"),
    BUDGET_LIMIT("budget_limit"),
    UNAVAILABLE("unavailable");

    companion object {
        fun of(raw: String?) = entries.firstOrNull { it.raw == raw }
    }
}

class SuggestionException(val failure: SuggestionFailure) : Exception(failure.raw)

/**
 * 요청 종류에 맞고 바로 보여줄 수 있는 후보만 받는다. 앞뒤 공백을 지운 후보를 돌려준다.
 * 공급자와 관계없는 규칙이다. 저장된 기록이 필요한 검사는 [ProgressFlow]가 한다. iOS `CandidatePolicy`와 같다.
 */
object CandidatePolicy {
    fun accept(candidate: SuggestionCandidate, request: SuggestionRequest): SuggestionCandidate? = when (candidate) {
        is SuggestionCandidate.InsufficientInfo ->
            trimmed(candidate.reason)?.takeIf { request.kind != SuggestionKind.GOAL_PREPARATION }
                ?.let(SuggestionCandidate::InsufficientInfo)
        is SuggestionCandidate.GoalSummary ->
            trimmed(candidate.criteria)?.takeIf { request.kind == SuggestionKind.GOAL_PREPARATION }
                ?.let(SuggestionCandidate::GoalSummary)
        SuggestionCandidate.NoAction -> candidate.takeIf { request.kind == SuggestionKind.REPLACEMENT }
        is SuggestionCandidate.Question -> trimmed(candidate.question)?.let(SuggestionCandidate::Question)
        is SuggestionCandidate.Action -> action(candidate.action, request)?.let(SuggestionCandidate::Action)
        is SuggestionCandidate.MinimalAction -> action(candidate.action, request)?.let(SuggestionCandidate::MinimalAction)
    }

    /**
     * 필수 필드가 비었거나 목표·원래 행동의 완료를 표시한 후보는 받지 않는다.
     * 더 작게는 현재 행동을, 다른 요청은 보류한 행동을 그대로 다시 제안하면 받지 않는다.
     */
    private fun action(proposed: ProposedAction, request: SuggestionRequest): ProposedAction? {
        if (request.kind == SuggestionKind.GOAL_PREPARATION) return null
        val task = trimmed(proposed.task) ?: return null
        val doneWhen = trimmed(proposed.doneWhen) ?: return null
        if (proposed.estimatedMinutes <= 0 || proposed.marksGoalComplete || proposed.marksCurrentActionComplete) return null
        if (!proposed.materialLinks.all(::isWebLink)) return null
        val excluded = if (request.kind == SuggestionKind.SMALLER) listOfNotNull(request.currentAction?.task) else request.deferredTasks
        if (task in excluded) return null
        return proposed.copy(
            task = task,
            doneWhen = doneWhen,
            targetName = proposed.targetName?.let(::trimmed),
            targetDescription = proposed.targetDescription?.let(::trimmed),
        )
    }

    /** http/https이고 호스트가 있는 링크만 자료 링크로 받는다. */
    fun isWebLink(link: String): Boolean = try {
        val uri = URI(link)
        uri.scheme?.lowercase() in setOf("http", "https") && !uri.host.isNullOrEmpty()
    } catch (_: Exception) {
        false
    }

    private fun trimmed(text: String) = text.trim().ifEmpty { null }
}

/** 실제 공급자를 연결하기 전에 쓰는 공급자다. 항상 `사용 불가`로 실패한다. */
object UnavailableSuggestionProvider : ActionSuggestionProvider {
    override suspend fun suggest(request: SuggestionRequest): SuggestionCandidate =
        throw SuggestionException(SuggestionFailure.UNAVAILABLE)
}

package dev.smallnext.app.progress

import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withContext

/** 목표 준비 요청은 목표 문장을 완료 조건으로 돌려준다. iOS `GoalPreparing`과 같다. */
fun goalPreparing(wrapped: ActionSuggestionProvider) = ActionSuggestionProvider { request ->
    if (request.kind == SuggestionKind.GOAL_PREPARATION) SuggestionCandidate.GoalSummary(request.goal) else wrapped.suggest(request)
}

/**
 * 결과를 차례로 돌려준다. iOS `ScriptedProvider`와 같다.
 * `gated`면 [release]마다 요청 하나를 풀어 준다. 대기 화면을 확인하는 테스트가 결과 도착 순서를 정한다.
 */
class ScriptedProvider(outcomes: List<Result<SuggestionCandidate>>, private val gated: Boolean = false) : ActionSuggestionProvider {
    constructor(vararg candidates: SuggestionCandidate, gated: Boolean = false) : this(candidates.map { Result.success(it) }, gated)

    private val outcomes = ArrayDeque(outcomes)
    private val gate = Channel<Unit>(Channel.UNLIMITED)
    val requests: MutableList<SuggestionRequest> = CopyOnWriteArrayList()

    fun release() {
        gate.trySend(Unit)
    }

    override suspend fun suggest(request: SuggestionRequest): SuggestionCandidate {
        requests.add(request)
        if (gated) gate.receive()
        val outcome = synchronized(outcomes) { outcomes.removeFirstOrNull() } ?: throw SuggestionException(SuggestionFailure.FAILED)
        return outcome.getOrThrow()
    }
}

/** [release] 전까지 결과를 붙잡는다. 취소를 무시해 늦게 도착한 결과를 만든다. iOS `HeldProvider`와 같다. */
class HeldProvider(private val candidate: SuggestionCandidate) : ActionSuggestionProvider {
    private val gate = CompletableDeferred<Unit>()
    val requests = AtomicInteger()

    fun release() {
        gate.complete(Unit)
    }

    override suspend fun suggest(request: SuggestionRequest): SuggestionCandidate {
        requests.incrementAndGet()
        withContext(NonCancellable) { gate.await() }
        return candidate
    }
}

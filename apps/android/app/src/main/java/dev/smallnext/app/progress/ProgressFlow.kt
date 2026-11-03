package dev.smallnext.app.progress

import android.database.Cursor
import android.util.Log
import androidx.sqlite.db.SimpleSQLiteQuery
import androidx.sqlite.db.SupportSQLiteDatabase
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import dev.smallnext.app.data.AppDatabase
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class GoalInput(
    val statement: String = "",
    val deadline: String = "",
    val currentState: String = "",
    val blocker: String = "",
    val materialLinks: String = "",
    val materialExcerpt: String = "",
    val availableMinutes: String = "",
)

/** 화면에 남은 입력 초안이다. 명령 전에 현재 화면에 해당하는 값만 저장한다(iOS `Drafts`). */
data class Drafts(val goalInput: GoalInput = GoalInput(), val answer: String = "", val completionCriteria: String = "")

/** 확인 질문의 답이나 수정 중인 완료 조건의 초안이다. [text]가 null이면 아직 저장한 초안이 없다. */
data class SuggestionInput(val requestId: Long, val text: String?)

data class GoalDetails(val id: Long, val statement: String, val completionCriteria: String?, val context: GoalContext)

data class ActionCard(val id: Long, val task: String, val doneWhen: String, val estimatedMinutes: Int)

sealed interface SuggestionProblem {
    data class Failure(val failure: SuggestionFailure) : SuggestionProblem
    /** 구조 검사를 통과하지 못했거나 아직 화면이 없는 후보다. */
    data object Unsuitable : SuggestionProblem
    /** 앱 종료 등으로 끝나지 않았거나 이전 상태에 대한 요청이다. */
    data object Interrupted : SuggestionProblem
    /** 사용자가 취소한 요청이다. */
    data object Cancelled : SuggestionProblem
}

/**
 * iOS `ProgressScreen` 중 이 단계에서 닿는 상태다. 대기 화면의 `problem`이 null이면 제안을 기다리는 중이다.
 * 정보 부족 안내·행동 질문·보류 중·목표 중단과 더 작게 상태는 해당 티켓(#353~#356)에서 더한다.
 */
sealed interface ProgressScreen {
    data object GoalInput : ProgressScreen
    data class PreparingGoal(val question: String?, val completionCriteria: String?, override val problem: SuggestionProblem?) : ProgressScreen
    /** 첫 행동을 받기 전이다. 입력한 목표를 유지한다. */
    data class AwaitingFirstAction(val goal: String, override val problem: SuggestionProblem?) : ProgressScreen
    data class CurrentAction(val card: ActionCard) : ProgressScreen
    /** 완료 후 다음 행동을 받기 전이다. 완료 기록을 유지한다. */
    data class AwaitingNextAction(override val problem: SuggestionProblem?) : ProgressScreen

    /** 실패·중단·취소한 제안의 문제다. '다시 시도'를 보여줄 때만 값이 있다. */
    val problem: SuggestionProblem? get() = null
}

/** 제안을 기다리는 중인지 나타낸다. 결과 저장에 실패한 요청은 실패로 보여 취소할 수 없다. */
val ProgressScreen.isWaitingForSuggestion: Boolean
    get() = when (this) {
        is ProgressScreen.PreparingGoal -> this == ProgressScreen.PreparingGoal(null, null, null)
        is ProgressScreen.AwaitingFirstAction, is ProgressScreen.AwaitingNextAction -> problem == null
        ProgressScreen.GoalInput, is ProgressScreen.CurrentAction -> false
    }

data class ProgressState(
    val screen: ProgressScreen,
    val goalInput: GoalInput,
    val goal: GoalDetails?,
    val suggestionInput: SuggestionInput? = null,
)

class ProgressFlowException(val reason: Reason) : RuntimeException(reason.name) {
    enum class Reason { EMPTY_GOAL, EMPTY_ANSWER, GOAL_INPUT_NOT_ACTIVE, INVALID_GOAL_CONTEXT, GOAL_NOT_READY, GOAL_NOT_FOUND }
}

/**
 * 화면이 호출하는 진행 흐름의 유일한 진입점이다. iOS `ProgressFlow`의 명령·조회·상태 규칙을 옮긴다.
 * - 명령마다 Room 트랜잭션 하나로 저장한다. 저장에 실패하면 [state]를 바꾸지 않는다.
 * - 명령과 제안 결과 적용은 한 번에 하나씩 차례로 실행한다. iOS는 메인 스레드 동기 실행으로 같은 효과를 얻는다.
 * - 제안 작업은 [scope]에서 돈다. 앱은 애플리케이션 수명의 scope를 넘겨 회전해도 요청이 이어지게 한다.
 */
class ProgressFlow private constructor(
    private val database: AppDatabase,
    private val provider: ActionSuggestionProvider,
    private val scope: CoroutineScope,
    initial: ProgressState,
) {
    private val _state = MutableStateFlow(initial)
    val state: StateFlow<ProgressState> = _state.asStateFlow()
    private val serial = Dispatchers.IO.limitedParallelism(1)
    @Volatile private var suggestionJob: Job? = null
    /** 결과 저장 실패로 DB에 pending이 남은 요청이다. 다음 성공한 명령에서 실패 상태도 저장한다. */
    private var unsavedSuggestionId: Long? = null

    /**
     * 사용자 명령 하나를 실행한다. 입력 초안을 먼저 저장한다(iOS `run(saving:)`).
     * 초안 저장에 실패하면 명령을 실행하지 않는다.
     * iOS와 달리 저장과 명령 사이에 제안 결과 적용이 끼어들 수 있다. 명령은 화면 상태를 다시 검사한다.
     */
    suspend fun run(drafts: Drafts? = null, command: suspend () -> Unit) {
        drafts?.let { save(it) }
        command()
    }

    private suspend fun save(drafts: Drafts) {
        state.value.suggestionInput?.let { input ->
            val criteria = (state.value.screen as? ProgressScreen.PreparingGoal)?.completionCriteria
            val (text, saved) = if (criteria != null) drafts.completionCriteria to (input.text ?: criteria) else drafts.answer to (input.text ?: "")
            if (text != saved) updateSuggestionInput(text, input.requestId)
        }
        if (state.value.screen == ProgressScreen.GoalInput && drafts.goalInput != state.value.goalInput) updateGoalInput(drafts.goalInput)
    }

    /** 제출하기 전의 입력도 그대로 저장한다. 입력 초안은 확인한 목표가 아니다. */
    suspend fun updateGoalInput(input: GoalInput) = serially { saveGoalInput(input) }

    private fun saveGoalInput(input: GoalInput) {
        if (state.value.screen != ProgressScreen.GoalInput) fail(ProgressFlowException.Reason.GOAL_INPUT_NOT_ACTIVE)
        database.write { db -> db.setMetadata(GOAL_INPUT, gson.toJson(input)) }
        _state.update { it.copy(goalInput = input) }
    }

    /** 확인 질문의 답과 수정 중인 완료 조건도 초안으로 보존한다. 이전 요청의 늦은 입력은 거부한다. */
    suspend fun updateSuggestionInput(text: String, requestId: Long) = serially {
        perform { db ->
            val goalId = selectedGoalId(db)
            if (goalId == null || loadSuggestionInput(db, goalId, loadScreen(db, goalId))?.requestId != requestId) {
                fail(ProgressFlowException.Reason.GOAL_NOT_READY)
            }
            db.setMetadata("$SUGGESTION_INPUT:$goalId", text)
            null
        }
    }

    /**
     * 선택 입력을 검사해 저장한다. 확인용 요약만 요청한다.
     * [draft]를 주면 검사 전에 초안으로 먼저 저장한다. 검사에 실패해도 초안은 남는다. 없으면 저장한 초안을 쓴다.
     */
    suspend fun prepareGoal(draft: GoalInput? = null) = serially {
        if (state.value.screen != ProgressScreen.GoalInput) fail(ProgressFlowException.Reason.GOAL_INPUT_NOT_ACTIVE)
        if (draft != null && draft != state.value.goalInput) saveGoalInput(draft)
        val input = state.value.goalInput
        val statement = input.statement.trim().ifEmpty { fail(ProgressFlowException.Reason.EMPTY_GOAL) }
        val links = input.materialLinks.lines().mapNotNull(::nonempty)
        val minutesText = input.availableMinutes.trim()
        val minutes = minutesText.toIntOrNull()
        if (!links.all(CandidatePolicy::isWebLink) || (minutesText.isNotEmpty() && (minutes ?: 0) <= 0)) {
            fail(ProgressFlowException.Reason.INVALID_GOAL_CONTEXT)
        }
        perform { db ->
            selectedGoalId(db)?.let { endPendingRequests(db, it, "interrupted") }
            val now = System.currentTimeMillis()
            val goalId = db.insert(
                """
                INSERT INTO goal (statement, deadline, current_state, blocker, materials, material_excerpt, available_minutes,
                                  completion_criteria, proposed_completion_criteria, is_confirmed, status, revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, 'active', 0, ?, ?)
                """,
                statement, nonempty(input.deadline), nonempty(input.currentState), nonempty(input.blocker),
                gson.toJson(links), nonempty(input.materialExcerpt), minutes, now, now,
            )
            db.update("UPDATE app_metadata SET `key` = ? WHERE `key` = ?", "$GOAL_INPUT:$goalId", GOAL_INPUT)
            db.setMetadata(SELECTED_GOAL_ID, goalId.toString())
            insertRequest(db, goalId, SuggestionKind.GOAL_PREPARATION)
        }
    }

    /** 사용자가 확인한 완료 조건만 확정한다. 그 뒤 첫 행동을 요청한다. */
    suspend fun confirmGoal(completionCriteria: String) = serially {
        val screen = state.value.screen
        if (screen !is ProgressScreen.PreparingGoal || screen.completionCriteria == null || screen.problem != null) {
            fail(ProgressFlowException.Reason.GOAL_NOT_READY)
        }
        val criteria = nonempty(completionCriteria) ?: fail(ProgressFlowException.Reason.GOAL_NOT_READY)
        perform { db ->
            val goalId = selectedGoalId(db) ?: fail(ProgressFlowException.Reason.GOAL_NOT_FOUND)
            val changed = db.update(
                "UPDATE goal SET completion_criteria = ?, is_confirmed = 1, proposed_completion_criteria = NULL " +
                    "WHERE id = ? AND NOT is_confirmed AND proposed_completion_criteria IS NOT NULL",
                criteria, goalId,
            )
            if (changed != 1) fail(ProgressFlowException.Reason.GOAL_NOT_READY)
            db.update("DELETE FROM app_metadata WHERE `key` = ?", "$GOAL_INPUT:$goalId")
            bumpRevision(db, goalId)
            insertRequest(db, goalId, SuggestionKind.FIRST_ACTION)
        }
    }

    /** 목표의 확인 질문 하나에 답한다. 답은 원래 질문과 함께 목표 맥락으로 보존한다. */
    suspend fun answerGoalQuestion(text: String) = serially {
        val screen = state.value.screen
        if (screen !is ProgressScreen.PreparingGoal || screen.question == null || screen.completionCriteria != null || screen.problem != null) {
            fail(ProgressFlowException.Reason.GOAL_NOT_READY)
        }
        val answer = nonempty(text) ?: fail(ProgressFlowException.Reason.EMPTY_ANSWER)
        perform { db ->
            val goalId = selectedGoalId(db) ?: fail(ProgressFlowException.Reason.GOAL_NOT_FOUND)
            val changed = db.update(
                "UPDATE suggestion_request SET answer = ? WHERE id = (SELECT MAX(id) FROM suggestion_request WHERE goal_id = ?) " +
                    "AND kind = ? AND question IS NOT NULL AND answer IS NULL AND status = 'applied'",
                answer, goalId, SuggestionKind.GOAL_PREPARATION.raw,
            )
            if (changed != 1) fail(ProgressFlowException.Reason.GOAL_NOT_READY)
            bumpRevision(db, goalId)
            insertRequest(db, goalId, SuggestionKind.GOAL_PREPARATION)
        }
    }

    /** 현재 행동만 완료한다. 이미 완료한 행동이나 지금 보이지 않는 행동에 대한 호출은 무시한다. */
    suspend fun complete(actionId: Long) = serially {
        if ((state.value.screen as? ProgressScreen.CurrentAction)?.card?.id != actionId) return@serially
        perform { db ->
            if (db.update("UPDATE action SET status = 'done' WHERE id = ? AND status = 'current'", actionId) != 1) return@perform null
            val goalId = db.long("SELECT goal_id FROM action WHERE id = ?", actionId) ?: return@perform null
            db.insert("INSERT INTO completion (action_id, completed_at) VALUES (?, ?)", actionId, System.currentTimeMillis())
            bumpRevision(db, goalId)
            // 다른 종류의 대기 요청은 이전 상태에 대한 요청이다. 완료를 막지 않도록 끝낸다.
            endPendingRequests(db, goalId, "interrupted")
            insertRequest(db, goalId, SuggestionKind.NEXT_ACTION)
        }
    }

    /** 실패·중단·취소한 제안만 다시 요청한다. 기다리는 중이면 무시한다. */
    suspend fun retrySuggestion() = serially {
        if (state.value.screen.problem == null) return@serially
        perform { db ->
            val goalId = selectedGoalId(db) ?: return@perform null
            val latest = SuggestionKind.of(db.string("SELECT kind FROM suggestion_request WHERE goal_id = ? ORDER BY id DESC LIMIT 1", goalId))
            // 결과 저장에 실패해 pending으로 남은 요청을 끝낸다. 늦게 온 결과는 적용하지 않는다.
            endPendingRequests(db, goalId, "interrupted")
            // 첫 행동·다음 행동은 같은 종류로 다시 요청한다. 그 밖에는 현재 행동이 없을 때 대체 요청이다.
            val kind = when (latest) {
                SuggestionKind.GOAL_PREPARATION -> SuggestionKind.GOAL_PREPARATION
                SuggestionKind.FIRST_ACTION, SuggestionKind.NEXT_ACTION, null ->
                    if (hasCompletion(db, goalId)) SuggestionKind.NEXT_ACTION else SuggestionKind.FIRST_ACTION
                SuggestionKind.SMALLER, SuggestionKind.REPLACEMENT -> SuggestionKind.REPLACEMENT
            }
            insertRequest(db, goalId, kind)
        }
    }

    /** 기다리는 중인 제안만 취소한다. 취소는 공급자 코루틴까지 전달하고, 그 뒤 도착한 결과는 적용하지 않는다. */
    suspend fun cancelSuggestion() = serially {
        if (!state.value.screen.isWaitingForSuggestion) return@serially
        perform { db ->
            selectedGoalId(db)?.let { endPendingRequests(db, it, "cancelled") }
            null
        }
        suggestionJob?.cancel()
    }

    /** 진행 중인 제안 요청이 끝날 때까지 기다린다. 테스트에서 쓴다. */
    internal suspend fun awaitSuggestion() {
        suggestionJob?.join()
    }

    // 제안 요청

    private class PendingSuggestion(val id: Long, val goalId: Long, val revision: Int, val request: SuggestionRequest)

    private suspend fun <T> serially(block: () -> T): T = withContext(serial) { block() }

    private fun perform(command: (SupportSQLiteDatabase) -> PendingSuggestion?) {
        val failedId = unsavedSuggestionId
        val (pending, state) = database.write { db ->
            failedId?.let {
                db.update(
                    "UPDATE suggestion_request SET status = 'failed', failure_reason = ? WHERE id = ? AND status = 'pending'",
                    SuggestionFailure.FAILED.raw, it,
                )
            }
            command(db) to loadState(db)
        }
        unsavedSuggestionId = null
        _state.value = state
        pending?.let(::start)
    }

    private fun start(pending: PendingSuggestion) {
        suggestionJob?.cancel()
        suggestionJob = scope.launch {
            val outcome = try {
                Result.success(provider.suggest(pending.request))
            } catch (error: CancellationException) {
                // 공급자 안의 시간 제한 등 이 작업의 취소가 아닌 취소 예외는 실패로 끝내 요청이 pending으로 남지 않게 한다.
                ensureActive()
                Result.failure(SuggestionException(SuggestionFailure.FAILED))
            } catch (error: SuggestionException) {
                Result.failure(error)
            } catch (_: Exception) {
                Result.failure(SuggestionException(SuggestionFailure.FAILED))
            }
            withContext(serial) { finish(pending, outcome) }
        }
    }

    private fun finish(pending: PendingSuggestion, outcome: Result<SuggestionCandidate>) {
        try {
            _state.value = database.write { db ->
                apply(db, pending, outcome)
                loadState(db)
            }
        } catch (error: Exception) {
            // 예외 메시지에는 원문이 담길 수 있어 클래스 이름만 남긴다.
            Log.e(TAG, "Suggestion result was not saved: ${error.javaClass.simpleName}")
            unsavedSuggestionId = pending.id
            val failed = SuggestionProblem.Failure(SuggestionFailure.FAILED)
            _state.update {
                it.copy(
                    screen = when (val screen = it.screen) {
                        is ProgressScreen.PreparingGoal -> if (screen == ProgressScreen.PreparingGoal(null, null, null)) screen.copy(problem = failed) else screen
                        is ProgressScreen.AwaitingFirstAction -> if (screen.problem == null) screen.copy(problem = failed) else screen
                        is ProgressScreen.AwaitingNextAction -> if (screen.problem == null) screen.copy(problem = failed) else screen
                        else -> screen
                    },
                )
            }
        }
    }

    companion object {
        private const val TAG = "Smallnext"
        private const val GOAL_INPUT = "goal_input"
        private const val SUGGESTION_INPUT = "suggestion_input"
        private const val SELECTED_GOAL_ID = "selected_goal_id"
        private const val UNSUITABLE = "unsuitable"
        private val gson = Gson()
        private val stringList = object : TypeToken<List<String>>() {}.type

        /** 대기 중이던 요청은 앱 종료·프로세스 회수로 끝나지 않은 요청이다. `interrupted`로 바꾼다. */
        suspend fun open(database: AppDatabase, provider: ActionSuggestionProvider, scope: CoroutineScope): ProgressFlow {
            val state = withContext(Dispatchers.IO) {
                database.write { db ->
                    db.update("UPDATE suggestion_request SET status = 'interrupted' WHERE status = 'pending'")
                    loadState(db)
                }
            }
            return ProgressFlow(database, provider, scope, state)
        }

        private fun fail(reason: ProgressFlowException.Reason): Nothing = throw ProgressFlowException(reason)

        private fun nonempty(text: String) = text.trim().ifEmpty { null }

        /**
         * 요청이 아직 `pending`이고 목표 리비전이 같을 때만 결과를 적용한다. 리비전이 바뀐 요청은 `interrupted`로 끝낸다.
         * 아직 화면이 없는 후보(행동 요청의 질문, 정보 부족, 대체 후보 없음)는 부적합으로 끝낸다(#354, #356).
         */
        private fun apply(db: SupportSQLiteDatabase, pending: PendingSuggestion, outcome: Result<SuggestionCandidate>) {
            val (status, revision) = db.query(
                "SELECT r.status, g.revision FROM suggestion_request r JOIN goal g ON g.id = r.goal_id WHERE r.id = ?",
                pending.id,
            ) { it.getString(0) to it.getInt(1) }.firstOrNull() ?: return
            if (status != "pending") return
            if (revision != pending.revision || selectedGoalId(db) != pending.goalId ||
                db.long("SELECT MAX(id) FROM suggestion_request WHERE goal_id = ?", pending.goalId) != pending.id
            ) {
                return finishRequest(db, pending.id, "interrupted", null)
            }
            val proposed = outcome.getOrElse {
                return finishRequest(db, pending.id, "failed", (it as SuggestionException).failure.raw)
            }
            val action = when (val candidate = CandidatePolicy.accept(proposed, pending.request)) {
                is SuggestionCandidate.GoalSummary -> {
                    db.update("UPDATE goal SET proposed_completion_criteria = ? WHERE id = ? AND NOT is_confirmed", candidate.criteria, pending.goalId)
                    return finishRequest(db, pending.id, "applied", null)
                }
                is SuggestionCandidate.Question -> {
                    // 이미 답한 질문은 다시 묻지 않는다.
                    val answered = db.long(
                        "SELECT EXISTS (SELECT 1 FROM suggestion_request WHERE goal_id = ? AND question = ? AND answer IS NOT NULL)",
                        pending.goalId, candidate.question,
                    ) == 1L
                    if (pending.request.kind != SuggestionKind.GOAL_PREPARATION || answered) {
                        return finishRequest(db, pending.id, "failed", UNSUITABLE)
                    }
                    db.update("UPDATE suggestion_request SET status = 'applied', question = ? WHERE id = ?", candidate.question, pending.id)
                    return
                }
                is SuggestionCandidate.Action -> candidate.action
                is SuggestionCandidate.MinimalAction -> candidate.action
                is SuggestionCandidate.InsufficientInfo, SuggestionCandidate.NoAction, null ->
                    return finishRequest(db, pending.id, "failed", UNSUITABLE)
            }
            db.insert(
                """
                INSERT INTO action (goal_id, task, done_when, estimated_minutes, reason, target_name, target_description,
                                    material_links, status, split_from_id, remaining_summary, sequence)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 'current', NULL, NULL, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM action WHERE goal_id = ?))
                """,
                pending.goalId, action.task, action.doneWhen, action.estimatedMinutes, action.targetName, action.targetDescription,
                gson.toJson(action.materialLinks), pending.goalId,
            )
            bumpRevision(db, pending.goalId)
            finishRequest(db, pending.id, "applied", null)
        }

        private fun finishRequest(db: SupportSQLiteDatabase, id: Long, status: String, reason: String?) {
            db.update("UPDATE suggestion_request SET status = ?, failure_reason = ? WHERE id = ?", status, reason, id)
        }

        private fun endPendingRequests(db: SupportSQLiteDatabase, goalId: Long, status: String) {
            db.update("UPDATE suggestion_request SET status = ? WHERE goal_id = ? AND status = 'pending'", status, goalId)
        }

        private fun bumpRevision(db: SupportSQLiteDatabase, goalId: Long) {
            db.update("UPDATE goal SET revision = revision + 1, updated_at = ? WHERE id = ?", System.currentTimeMillis(), goalId)
        }

        private fun insertRequest(db: SupportSQLiteDatabase, goalId: Long, kind: SuggestionKind): PendingSuggestion {
            val revision = db.long("SELECT revision FROM goal WHERE id = ?", goalId)?.toInt() ?: fail(ProgressFlowException.Reason.GOAL_NOT_FOUND)
            db.update("DELETE FROM app_metadata WHERE `key` = ?", "$SUGGESTION_INPUT:$goalId")
            val id = db.insert(
                "INSERT INTO suggestion_request (goal_id, kind, goal_revision, status, failure_reason, question, answer, created_at) " +
                    "VALUES (?, ?, ?, 'pending', NULL, NULL, NULL, ?)",
                goalId, kind.raw, revision, System.currentTimeMillis(),
            )
            return PendingSuggestion(id, goalId, revision, makeRequest(db, goalId, revision, kind))
        }

        private fun makeRequest(db: SupportSQLiteDatabase, goalId: Long, revision: Int, kind: SuggestionKind): SuggestionRequest {
            val details = loadGoalDetails(db, goalId)!!
            val completed = "FROM completion c JOIN action a ON a.id = c.action_id WHERE a.goal_id = ? ORDER BY c.id"
            return SuggestionRequest(
                kind = kind,
                goal = details.statement,
                currentAction = contextAction(db, goalId, kind),
                completedTasks = db.strings("SELECT a.task $completed", goalId),
                blocker = db.string("SELECT blocker FROM goal WHERE id = ?", goalId),
                deferredTasks = db.strings("SELECT task FROM action WHERE goal_id = ? AND status = 'deferred' ORDER BY sequence", goalId),
                context = details.context,
                completionCriteria = details.completionCriteria,
                stateKey = "$goalId:$revision",
                remainingTasks = db.strings(
                    "SELECT task FROM action WHERE goal_id = ? AND status IN ('current', 'split', 'deferred') ORDER BY sequence", goalId,
                ),
                completedActionIds = db.strings("SELECT a.id $completed", goalId),
                actionAnswers = answers(db, goalId, goalPreparation = false),
            )
        }

        /** 다음 행동은 방금 완료한 작은 행동의 분할 원본을 담는다. 더 작게는 #353에서 현재 행동을 담는다. */
        private fun contextAction(db: SupportSQLiteDatabase, goalId: Long, kind: SuggestionKind): ProposedAction? {
            if (kind != SuggestionKind.NEXT_ACTION) return null
            return db.query(
                """
                SELECT p.task, p.done_when, p.estimated_minutes FROM completion c
                JOIN action a ON a.id = c.action_id
                LEFT JOIN action p ON p.id = a.split_from_id AND p.status = 'split'
                WHERE a.goal_id = ? ORDER BY c.id DESC LIMIT 1
                """,
                goalId,
            ) { if (it.isNull(0)) null else ProposedAction(it.getString(0), it.getString(1), it.getInt(2)) }.firstOrNull()
        }

        /** 목표 준비 질문의 답과 행동 요청 질문의 답을 나눠 읽는다. */
        private fun answers(db: SupportSQLiteDatabase, goalId: Long, goalPreparation: Boolean) = db.query(
            "SELECT question, answer FROM suggestion_request WHERE goal_id = ? AND (kind = ?) = ? AND answer IS NOT NULL ORDER BY id",
            goalId, SuggestionKind.GOAL_PREPARATION.raw, goalPreparation,
        ) { GoalAnswer(it.getString(0), it.getString(1)) }

        // 화면 상태

        private fun loadState(db: SupportSQLiteDatabase): ProgressState {
            val goalId = selectedGoalId(db)
            val screen = loadScreen(db, goalId)
            return ProgressState(
                screen, loadGoalInput(db, goalId), goalId?.let { loadGoalDetails(db, it) }, goalId?.let { loadSuggestionInput(db, it, screen) },
            )
        }

        /** 확인 질문이나 확인할 완료 조건이 보이는 동안만 초안을 받는다. 행동 질문은 #354에서 더한다. */
        private fun loadSuggestionInput(db: SupportSQLiteDatabase, goalId: Long, screen: ProgressScreen): SuggestionInput? {
            if (screen !is ProgressScreen.PreparingGoal || screen.problem != null || (screen.question == null && screen.completionCriteria == null)) {
                return null
            }
            val requestId = db.long("SELECT MAX(id) FROM suggestion_request WHERE goal_id = ?", goalId) ?: return null
            return SuggestionInput(requestId, db.string("SELECT value FROM app_metadata WHERE `key` = ?", "$SUGGESTION_INPUT:$goalId"))
        }

        private fun selectedGoalId(db: SupportSQLiteDatabase) =
            db.string("SELECT value FROM app_metadata WHERE `key` = ?", SELECTED_GOAL_ID)?.toLongOrNull()

        /** 확인 중인 목표는 그 목표의 입력을, 그 밖에는 새 목표 입력을 복구한다. */
        private fun loadGoalInput(db: SupportSQLiteDatabase, goalId: Long?): GoalInput {
            val reviewing = goalId != null && db.long("SELECT NOT is_confirmed FROM goal WHERE id = ?", goalId) == 1L
            val text = db.string("SELECT value FROM app_metadata WHERE `key` = ?", if (reviewing) "$GOAL_INPUT:$goalId" else GOAL_INPUT)
            return text?.let { gson.fromJson(it, GoalInput::class.java) } ?: GoalInput()
        }

        private fun loadGoalDetails(db: SupportSQLiteDatabase, goalId: Long): GoalDetails? = db.query(
            "SELECT statement, completion_criteria, deadline, current_state, materials, material_excerpt, available_minutes FROM goal WHERE id = ?",
            goalId,
        ) {
            GoalDetails(
                id = goalId,
                statement = it.getString(0),
                completionCriteria = it.optString(1),
                context = GoalContext(
                    deadline = it.optString(2),
                    currentState = it.optString(3),
                    materialLinks = it.optString(4)?.let { links -> gson.fromJson<List<String>>(links, stringList) }.orEmpty(),
                    materialExcerpt = it.optString(5),
                    availableMinutes = if (it.isNull(6)) null else it.getInt(6),
                ),
            )
        }.firstOrNull()?.let { it.copy(context = it.context.copy(answers = answers(db, goalId, goalPreparation = true))) }

        private fun hasCompletion(db: SupportSQLiteDatabase, goalId: Long) =
            db.long("SELECT EXISTS (SELECT 1 FROM action WHERE goal_id = ? AND status = 'done')", goalId) == 1L

        private fun loadScreen(db: SupportSQLiteDatabase, goalId: Long?): ProgressScreen {
            goalId ?: return ProgressScreen.GoalInput
            val (statement, confirmed, proposed) = db.query(
                "SELECT statement, is_confirmed, proposed_completion_criteria FROM goal WHERE id = ?", goalId,
            ) { Triple(it.getString(0), it.getInt(1) == 1, it.optString(2)) }.firstOrNull() ?: return ProgressScreen.GoalInput
            val latest = db.query(
                "SELECT status, failure_reason, question FROM suggestion_request WHERE goal_id = ? ORDER BY id DESC LIMIT 1", goalId,
            ) { Triple(it.getString(0), it.optString(1), it.optString(2)) }.firstOrNull()
            // 요청이 없으면 이전 상태에 대한 요청처럼 다시 시도를 기다린다.
            val problem = if (latest == null) SuggestionProblem.Interrupted else requestProblem(latest.first, latest.second)
            if (!confirmed) return ProgressScreen.PreparingGoal(latest?.third, proposed, problem)
            db.query(
                "SELECT id, task, done_when, estimated_minutes FROM action WHERE goal_id = ? AND status = 'current'", goalId,
            ) { ActionCard(it.getLong(0), it.getString(1), it.getString(2), it.getInt(3)) }.firstOrNull()
                ?.let { return ProgressScreen.CurrentAction(it) }
            if (hasCompletion(db, goalId)) return ProgressScreen.AwaitingNextAction(problem)
            return ProgressScreen.AwaitingFirstAction(statement, problem)
        }

        /** 끝나지 않았거나 적용한 요청이면 null이다. */
        private fun requestProblem(status: String, reason: String?): SuggestionProblem? = when (status) {
            "pending", "applied" -> null
            "failed" -> SuggestionFailure.of(reason)?.let(SuggestionProblem::Failure) ?: SuggestionProblem.Unsuitable
            "cancelled" -> SuggestionProblem.Cancelled
            else -> SuggestionProblem.Interrupted
        }

        // SQL 도우미. iOS GRDB의 SQL을 그대로 옮기려고 Room DAO 대신 SupportSQLiteDatabase를 쓴다.

        private fun <T> AppDatabase.write(block: (SupportSQLiteDatabase) -> T): T =
            runInTransaction<T> { block(openHelper.writableDatabase) }

        private fun SupportSQLiteDatabase.update(sql: String, vararg args: Any?): Int =
            compileStatement(sql).use { SimpleSQLiteQuery.bind(it, args); it.executeUpdateDelete() }

        private fun SupportSQLiteDatabase.insert(sql: String, vararg args: Any?): Long =
            compileStatement(sql).use { SimpleSQLiteQuery.bind(it, args); it.executeInsert() }

        /** `app_metadata`에는 트리거가 없어 덮어쓰기를 쓴다. API 26의 SQLite는 UPSERT 문법이 없다. */
        private fun SupportSQLiteDatabase.setMetadata(key: String, value: String) {
            update("INSERT OR REPLACE INTO app_metadata (`key`, value) VALUES (?, ?)", key, value)
        }

        private fun <T> SupportSQLiteDatabase.query(sql: String, vararg args: Any?, row: (Cursor) -> T): List<T> =
            query(SimpleSQLiteQuery(sql, args)).use { cursor -> buildList { while (cursor.moveToNext()) add(row(cursor)) } }

        private fun SupportSQLiteDatabase.long(sql: String, vararg args: Any?): Long? =
            query(sql, *args) { if (it.isNull(0)) null else it.getLong(0) }.firstOrNull()

        private fun SupportSQLiteDatabase.string(sql: String, vararg args: Any?): String? =
            query(sql, *args) { it.optString(0) }.firstOrNull()

        private fun SupportSQLiteDatabase.strings(sql: String, vararg args: Any?): List<String> = query(sql, *args) { it.getString(0) }

        private fun Cursor.optString(index: Int): String? = if (isNull(index)) null else getString(index)
    }
}

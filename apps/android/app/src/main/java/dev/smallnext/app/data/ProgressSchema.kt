package dev.smallnext.app.data

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey
import androidx.sqlite.db.SupportSQLiteDatabase

// iOS AppDatabase의 progress_v1~v5 최종 형태. 시각은 epoch 밀리초, 자료 링크는 JSON 문자열이다.

@Entity(tableName = "goal")
data class GoalEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val statement: String,
    val deadline: String?,
    @ColumnInfo(name = "current_state") val currentState: String?,
    val blocker: String?,
    val materials: String?,
    @ColumnInfo(name = "material_excerpt") val materialExcerpt: String?,
    @ColumnInfo(name = "available_minutes") val availableMinutes: Int?,
    @ColumnInfo(name = "completion_criteria") val completionCriteria: String?,
    @ColumnInfo(name = "proposed_completion_criteria") val proposedCompletionCriteria: String?,
    @ColumnInfo(name = "is_confirmed") val isConfirmed: Boolean,
    val status: String,
    val revision: Int,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

@Entity(
    tableName = "action",
    foreignKeys = [
        ForeignKey(GoalEntity::class, ["id"], ["goal_id"], onDelete = ForeignKey.CASCADE),
        ForeignKey(ActionEntity::class, ["id"], ["split_from_id"], onDelete = ForeignKey.SET_NULL),
    ],
    indices = [Index("goal_id"), Index("split_from_id")],
)
data class ActionEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "goal_id") val goalId: Long,
    val task: String,
    @ColumnInfo(name = "done_when") val doneWhen: String,
    @ColumnInfo(name = "estimated_minutes") val estimatedMinutes: Int,
    val reason: String?,
    @ColumnInfo(name = "target_name") val targetName: String?,
    @ColumnInfo(name = "target_description") val targetDescription: String?,
    @ColumnInfo(name = "material_links") val materialLinks: String,
    val status: String,
    @ColumnInfo(name = "split_from_id") val splitFromId: Long?,
    @ColumnInfo(name = "remaining_summary") val remainingSummary: String?,
    val sequence: Int,
)

@Entity(
    tableName = "action_note",
    foreignKeys = [ForeignKey(ActionEntity::class, ["id"], ["action_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("action_id")],
)
data class ActionNoteEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "action_id") val actionId: Long,
    val body: String,
    @ColumnInfo(name = "is_draft") val isDraft: Boolean,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

@Entity(
    tableName = "completion",
    foreignKeys = [ForeignKey(ActionEntity::class, ["id"], ["action_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("action_id", unique = true, name = "completion_one_per_action")],
)
data class CompletionEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "action_id") val actionId: Long,
    @ColumnInfo(name = "completed_at") val completedAt: Long,
)

@Entity(
    tableName = "suggestion_request",
    foreignKeys = [ForeignKey(GoalEntity::class, ["id"], ["goal_id"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("goal_id")],
)
data class SuggestionRequestEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "goal_id") val goalId: Long,
    val kind: String,
    @ColumnInfo(name = "goal_revision") val goalRevision: Int,
    val status: String,
    @ColumnInfo(name = "failure_reason") val failureReason: String?,
    val question: String?,
    val answer: String?,
    @ColumnInfo(name = "created_at") val createdAt: Long,
)

/**
 * iOS의 CHECK와 부분 유일 인덱스는 Room 엔티티로 표현할 수 없고, 추가 인덱스는 Room 스키마 검증에 걸린다.
 * 그래서 Room이 검사하지 않는 트리거로 같은 규칙을 둔다. 새로 만든 DB와 v1에서 올린 DB 모두에 적용한다.
 * 트리거는 `ON CONFLICT`·`OnConflictStrategy`의 대상이 아니므로 iOS의 upsert는 조회 후 UPDATE/INSERT로 옮긴다.
 * 테이블을 다시 만드는 이후 마이그레이션은 트리거를 지우므로 이 함수를 다시 호출한다.
 */
internal fun createProgressIntegrity(db: SupportSQLiteDatabase) {
    listOf(
        statusIn("goal", "'active', 'stopped'"),
        statusIn("action", "'current', 'done', 'deferred', 'split'"),
        statusIn("suggestion_request", "'pending', 'applied', 'failed', 'interrupted', 'cancelled'"),
        onlyOne("action_one_current", "action", "goal_id", "status = 'current'"),
        onlyOne("suggestion_request_one_pending", "suggestion_request", "goal_id", "status = 'pending'"),
        onlyOne("action_note_one_draft", "action_note", "action_id", "is_draft"),
    ).flatten().forEach(db::execSQL)
}

private fun statusIn(table: String, allowed: String) = listOf("INSERT", "UPDATE OF status").map { event ->
    "CREATE TRIGGER IF NOT EXISTS ${table}_status_${event.substringBefore(' ').lowercase()} BEFORE $event ON `$table` " +
        "WHEN NEW.status NOT IN ($allowed) BEGIN SELECT RAISE(ABORT, '${table}_status'); END"
}

/** `parent`마다 `condition`을 만족하는 행을 하나만 허용한다. 조건 열 이름에 `NEW.`를 붙여 새 행을 검사한다. */
private fun onlyOne(name: String, table: String, parent: String, condition: String) = listOf(
    "INSERT" to "",
    "UPDATE" to " AND id != OLD.id",
).map { (event, notSelf) ->
    "CREATE TRIGGER IF NOT EXISTS ${name}_${event.lowercase()} BEFORE $event ON `$table` " +
        "WHEN NEW.$condition AND EXISTS (SELECT 1 FROM `$table` WHERE $parent = NEW.$parent AND $condition$notSelf) " +
        "BEGIN SELECT RAISE(ABORT, '$name'); END"
}

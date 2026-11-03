package dev.smallnext.app

import android.content.Context
import android.database.sqlite.SQLiteConstraintException
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.data.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ProgressSchemaTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val name = "smallnext-test-${java.util.UUID.randomUUID()}.sqlite"

    // iOS testProductMigrationKeepsBootstrapMetadata 대응. 버전 1 앱이 남긴 파일(schemas/…/1.json)을 Room이 올리고 검증한다.
    @Test
    fun productMigrationKeepsBootstrapMetadata() = runBlocking {
        try {
            context.openOrCreateDatabase(name, Context.MODE_PRIVATE, null).use { v1 ->
                v1.execSQL("CREATE TABLE IF NOT EXISTS `app_metadata` (`key` TEXT NOT NULL, `value` TEXT NOT NULL, PRIMARY KEY(`key`))")
                v1.execSQL("CREATE TABLE IF NOT EXISTS room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                v1.execSQL("INSERT OR REPLACE INTO room_master_table (id,identity_hash) VALUES(42, 'eb0bbe18501ebcc5d9f62aa645a0589c')")
                v1.execSQL("INSERT INTO app_metadata (`key`, value) VALUES ('schema_version', '1'), ('test', 'persistent')")
                v1.version = 1
            }

            val migrated = AppDatabase.open(context, name)
            try {
                migrated.metadata().initialize()
                assertEquals("1", migrated.metadata().value("schema_version"))
                assertEquals("persistent", migrated.metadata().value("test"))
                assertProgressIntegrity(migrated.openHelper.writableDatabase)
            } finally {
                migrated.close()
            }
        } finally {
            context.deleteDatabase(name)
        }
    }

    @Test
    fun newDatabaseHasTheSameIntegrityRules() {
        val database = AppDatabase.open(context, name)
        try {
            assertProgressIntegrity(database.openHelper.writableDatabase)
        } finally {
            database.close()
            context.deleteDatabase(name)
        }
    }

    private fun assertProgressIntegrity(db: SupportSQLiteDatabase) {
        db.execSQL(goal("active"))
        db.rejects(goal("archived"))
        db.rejects("UPDATE goal SET status = 'done' WHERE id = 1")

        db.execSQL(action(goal = 1, status = "current"))
        db.rejects(action(goal = 1, status = "current"))
        db.rejects(action(goal = 1, status = "todo"))
        db.execSQL(action(goal = 1, status = "deferred", splitFrom = 1))
        db.rejects("UPDATE action SET status = 'current' WHERE id = 2")
        db.rejects("UPDATE action SET status = 'todo' WHERE id = 2")
        db.execSQL("UPDATE action SET task = '고친 행동' WHERE id = 1")

        db.execSQL(request("pending"))
        db.rejects(request("pending"))
        db.rejects(request("waiting"))
        db.execSQL(request("failed"))
        db.rejects("UPDATE suggestion_request SET status = 'pending' WHERE id = 2")
        db.rejects("UPDATE suggestion_request SET status = 'waiting' WHERE id = 2")

        db.execSQL(note(action = 1, draft = true))
        db.rejects(note(action = 1, draft = true))
        db.execSQL(note(action = 1, draft = false))
        db.rejects("UPDATE action_note SET is_draft = 1 WHERE id = 2")

        db.execSQL(completion(action = 2))
        db.rejects(completion(action = 2))

        db.execSQL("DELETE FROM action WHERE id = 1")
        assertEquals(0L, db.count("action_note"))
        assertEquals(1L, db.count("action WHERE split_from_id IS NULL"))

        db.execSQL("DELETE FROM goal WHERE id = 1")
        listOf("action", "completion", "suggestion_request").forEach { assertEquals(it, 0L, db.count(it)) }
    }

    private fun goal(status: String) =
        "INSERT INTO goal (statement, is_confirmed, status, revision, created_at, updated_at) " +
            "VALUES ('목표', 1, '$status', 0, 0, 0)"

    private fun action(goal: Long, status: String, splitFrom: Long? = null) =
        "INSERT INTO action (goal_id, task, done_when, estimated_minutes, material_links, status, split_from_id, sequence) " +
            "VALUES ($goal, '행동', '끝', 5, '[]', '$status', $splitFrom, 0)"

    private fun request(status: String) =
        "INSERT INTO suggestion_request (goal_id, kind, goal_revision, status, created_at) " +
            "VALUES (1, 'nextAction', 0, '$status', 0)"

    private fun note(action: Long, draft: Boolean) =
        "INSERT INTO action_note (action_id, body, is_draft, updated_at) VALUES ($action, '메모', ${if (draft) 1 else 0}, 0)"

    private fun completion(action: Long) = "INSERT INTO completion (action_id, completed_at) VALUES ($action, 0)"

    private fun SupportSQLiteDatabase.rejects(sql: String) {
        assertThrows(sql, SQLiteConstraintException::class.java) { execSQL(sql) }
    }

    private fun SupportSQLiteDatabase.count(from: String) =
        query("SELECT COUNT(*) FROM $from").use { it.moveToFirst(); it.getLong(0) }
}

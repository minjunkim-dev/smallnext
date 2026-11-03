package dev.smallnext.app.data

import android.content.Context
import androidx.room.AutoMigration
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.AutoMigrationSpec
import androidx.sqlite.db.SupportSQLiteDatabase

@Entity(tableName = "app_metadata")
data class AppMetadata(@PrimaryKey val key: String, val value: String)

@Dao
interface MetadataDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(metadata: AppMetadata)

    @Query("SELECT value FROM app_metadata WHERE `key` = :key")
    suspend fun value(key: String): String?

    suspend fun initialize() = insert(AppMetadata("schema_version", "1"))
}

// 진행 테이블은 플래그와 관계없이 버전 2에서 생긴다. OFF 경로는 읽지 않는다.
@Database(
    entities = [
        AppMetadata::class,
        GoalEntity::class,
        ActionEntity::class,
        ActionNoteEntity::class,
        CompletionEntity::class,
        SuggestionRequestEntity::class,
    ],
    version = 2,
    exportSchema = true,
    autoMigrations = [AutoMigration(from = 1, to = 2, spec = AppDatabase.ProgressMigration::class)],
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun metadata(): MetadataDao

    class ProgressMigration : AutoMigrationSpec {
        override fun onPostMigrate(db: SupportSQLiteDatabase) = createProgressIntegrity(db)
    }

    companion object {
        fun open(context: Context, name: String = "smallnext.sqlite"): AppDatabase =
            Room.databaseBuilder(context.applicationContext, AppDatabase::class.java, name)
                .addCallback(object : Callback() {
                    override fun onCreate(db: SupportSQLiteDatabase) = createProgressIntegrity(db)
                })
                .build()
    }
}

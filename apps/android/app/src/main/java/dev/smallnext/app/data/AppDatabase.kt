package dev.smallnext.app.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase

@Entity(tableName = "app_metadata")
data class AppMetadata(@PrimaryKey val key: String, val value: String)

@Dao
interface MetadataDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(metadata: AppMetadata)

    @Query("SELECT value FROM app_metadata WHERE \u0060key\u0060 = :key")
    suspend fun value(key: String): String?

    suspend fun initialize() = insert(AppMetadata("schema_version", "1"))
}

@Database(entities = [AppMetadata::class], version = 1, exportSchema = true)
abstract class AppDatabase : RoomDatabase() {
    abstract fun metadata(): MetadataDao

    companion object {
        fun open(context: Context, name: String = "smallnext.sqlite"): AppDatabase =
            Room.databaseBuilder(context.applicationContext, AppDatabase::class.java, name)
                .build()
    }
}

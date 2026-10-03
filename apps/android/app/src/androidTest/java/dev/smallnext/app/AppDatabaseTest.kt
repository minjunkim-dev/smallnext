package dev.smallnext.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.smallnext.app.data.AppDatabase
import dev.smallnext.app.data.AppMetadata
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AppDatabaseTest {
    @Test
    fun bootstrapAndWritesSurviveReopening() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val name = "smallnext-test-${java.util.UUID.randomUUID()}.sqlite"
        try {
            val first = AppDatabase.open(context, name)
            first.metadata().initialize()
            first.metadata().insert(AppMetadata("test", "persistent"))
            first.close()

            val reopened = AppDatabase.open(context, name)
            try {
                reopened.metadata().initialize()
                assertEquals("1", reopened.metadata().value("schema_version"))
                assertEquals("persistent", reopened.metadata().value("test"))
            } finally {
                reopened.close()
            }
        } finally {
            context.deleteDatabase(name)
        }
    }
}

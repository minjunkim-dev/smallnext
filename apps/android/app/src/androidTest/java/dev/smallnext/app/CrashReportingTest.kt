package dev.smallnext.app

import android.content.pm.PackageManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.firebase.FirebaseApp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

// iOS CrashReportingTests 대응. testBundledCrashReportingFlagIsOff는 FeatureFlagsBundleTest.bundledCoreFlowIsOff가 맡는다.
// 유효한 설정으로 start를 부르지 않는다. 테스트 프로세스에서 Crashlytics를 켜지 않는다.
@RunWith(AndroidJUnit4::class)
class CrashReportingTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val valid = FirebaseConfig(
        appId = "1:123456789:android:abc123",
        senderId = "123456789",
        projectId = "smallnext-test",
        apiKey = "AIza" + "A".repeat(35),
    )

    @Test
    fun automaticCollectionIsDisabledInAppManifest() {
        val pm = context.packageManager
        val meta = pm.getApplicationInfo(context.packageName, PackageManager.GET_META_DATA).metaData
        assertFalse(meta.getBoolean("firebase_crashlytics_collection_enabled", true))
        assertFalse(meta.getBoolean("firebase_data_collection_default_enabled", true))
        val providers = pm.getPackageInfo(context.packageName, PackageManager.GET_PROVIDERS).providers.orEmpty()
        assertTrue(providers.none { it.name == "com.google.firebase.provider.FirebaseInitProvider" })
    }

    @Test
    fun validClientOptionsPreserveProjectAndAppIdentity() {
        val options = requireNotNull(valid.options())
        assertEquals("1:123456789:android:abc123", options.applicationId)
        assertEquals("123456789", options.gcmSenderId)
        assertEquals("smallnext-test", options.projectId)
        assertEquals("AIza" + "A".repeat(35), options.apiKey)
    }

    @Test
    fun offAndInvalidSettingsNeverInitializeFirebase() {
        assertTrue(FirebaseApp.getApps(context).isEmpty())
        assertFalse(CrashReporting.start(context, enabled = false, config = valid))
        val fields = listOf<(FirebaseConfig, String) -> FirebaseConfig>(
            { c, v -> c.copy(appId = v) },
            { c, v -> c.copy(senderId = v) },
            { c, v -> c.copy(projectId = v) },
            { c, v -> c.copy(apiKey = v) },
        )
        for ((index, field) in fields.withIndex()) {
            for (invalid in listOf("", "\$(UNSET)", "invalid value", " ")) {
                assertFalse("$index $invalid", CrashReporting.start(context, enabled = true, config = field(valid, invalid)))
            }
        }
        for (invalid in listOf(
            valid.copy(appId = "1:123456789:ios:abc123"),
            valid.copy(senderId = "987654321"),
            valid.copy(apiKey = "AIza-short"),
            valid.copy(projectId = "UPPER-case"),
        )) {
            assertFalse(invalid.toString(), CrashReporting.start(context, enabled = true, config = invalid))
        }
        assertTrue(FirebaseApp.getApps(context).isEmpty())
    }
}

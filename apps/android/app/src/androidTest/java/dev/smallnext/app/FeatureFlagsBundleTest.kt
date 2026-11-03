package dev.smallnext.app

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

// 레지스트리는 앱 asset으로 들어가므로 기기에서 확인한다. iOS FeatureFlagsBundleTests 대응.
@RunWith(AndroidJUnit4::class)
class FeatureFlagsBundleTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val off = FeatureFlags(coreFlow = false, serverAI = false, crashReporting = false)

    @Test
    fun bundledCoreFlowIsOff() {
        assertEquals(off, FeatureFlags.forLaunch(context, null))
    }

    @Test
    fun iOSUserServerAIDoesNotChangeAndroidFlags() {
        val bundled = context.assets.open("feature-flags.json").bufferedReader().use { it.readText() }
        val root = JsonParser.parseString(bundled).asJsonObject
        val flags = root.getAsJsonArray("flags")
        val userServerAI = flags.map { it.asJsonObject }.single { it["key"].asString == "user_server_ai" }

        userServerAI.addProperty("default", true)
        assertEquals(off, FeatureFlags.resolve(root.toString(), emptyMap(), debug = false))
        flags.remove(userServerAI)
        assertEquals(off, FeatureFlags.resolve(root.toString(), emptyMap(), debug = false))
    }

    @Test
    fun debugLaunchExtraTurnsAndroidFlagOn() {
        val launch = Intent()
            .putExtra(FeatureFlags.CORE_FLOW, true)
            .putExtra("user_server_ai", true)
        assertEquals(off.copy(coreFlow = true), FeatureFlags.forLaunch(context, launch))
    }
}

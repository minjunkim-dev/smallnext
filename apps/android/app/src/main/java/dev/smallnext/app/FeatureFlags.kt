package dev.smallnext.app

import android.content.Context
import android.content.Intent
import com.google.gson.JsonParser
import com.google.gson.Strictness
import com.google.gson.stream.JsonReader
import com.google.gson.stream.JsonToken
import java.io.IOException
import java.io.StringReader

/** Android 플래그만 담는다. iOS 플래그(`ios_core_flow`, `user_server_ai` 등)는 읽지 않는다. */
data class FeatureFlags(val coreFlow: Boolean, val serverAI: Boolean, val crashReporting: Boolean) {
    companion object {
        const val CORE_FLOW = "android_core_flow"
        const val SERVER_AI = "android_server_ai"
        const val CRASH_REPORTING = "android_crash_reporting"
        private val keys = listOf(CORE_FLOW, SERVER_AI, CRASH_REPORTING)

        /** iOS `FeatureFlags.isEnabled`와 같은 규칙: 레지스트리 전체가 형식에 맞고 키가 하나일 때만 기본값을 쓴다. */
        fun isEnabled(key: String, registry: String?): Boolean {
            val flags = try {
                val reader = JsonReader(StringReader(registry ?: return false)).apply { strictness = Strictness.STRICT }
                val root = JsonParser.parseReader(reader).asJsonObject
                check(reader.peek() == JsonToken.END_DOCUMENT)
                val version = root.getAsJsonPrimitive("version")
                check(version.isNumber && version.asDouble == 1.0)
                root.getAsJsonArray("flags").map { element ->
                    val flag = element.asJsonObject
                    val name = flag.getAsJsonPrimitive("key")
                    val default = flag.getAsJsonPrimitive("default")
                    check(name.isString && default.isBoolean)
                    name.asString to default.asBoolean
                }
            } catch (_: Exception) {
                return false
            }
            return flags.singleOrNull { it.first == key }?.second ?: false
        }

        /** Debug만 실행 인텐트 extra로 덮어쓴다. Release는 레지스트리 기본값만 따른다. */
        fun resolve(registry: String?, overrides: Map<String, Boolean>, debug: Boolean): FeatureFlags {
            fun flag(key: String) = (if (debug) overrides[key] else null) ?: isEnabled(key, registry)
            return FeatureFlags(flag(CORE_FLOW), flag(SERVER_AI), flag(CRASH_REPORTING))
        }

        /** 예: `adb shell am start -n dev.smallnext.app/.MainActivity --ez android_core_flow true` */
        fun forLaunch(context: Context, intent: Intent?): FeatureFlags {
            val registry = try {
                context.assets.open("feature-flags.json").bufferedReader().use { it.readText() }
            } catch (_: IOException) {
                null
            }
            val overrides = intent?.let { launch ->
                keys.filter(launch::hasExtra).associateWith { launch.getBooleanExtra(it, false) }
            }.orEmpty()
            return resolve(registry, overrides, BuildConfig.DEBUG)
        }
    }
}

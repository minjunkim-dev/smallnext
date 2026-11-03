package dev.smallnext.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

// iOS FeatureFlagsTests와 같은 이름·기대 결과를 쓴다.
class FeatureFlagsTest {
    private val key = FeatureFlags.CORE_FLOW

    @Test
    fun nilRegistryIsOff() {
        assertFalse(FeatureFlags.isEnabled(key, null))
    }

    @Test
    fun brokenJSONIsOff() {
        assertFalse(FeatureFlags.isEnabled(key, ""))
        assertFalse(FeatureFlags.isEnabled(key, "{"))
        assertFalse(FeatureFlags.isEnabled(key, """{"version":1,"flags":[{"key":"$key","default":true}]} x"""))
        assertFalse(FeatureFlags.isEnabled(key, """{version:1,flags:[{key:"$key","default":true}]}"""))
    }

    @Test
    fun missingKeyIsOff() {
        assertFalse(FeatureFlags.isEnabled(key, """{"version":1,"flags":[{"key":"other","default":true}]}"""))
    }

    @Test
    fun duplicateKeyIsOff() {
        val registry = """
            {"version":1,"flags":[
              {"key":"$key","default":true},
              {"key":"$key","default":false}
            ]}
        """
        assertFalse(FeatureFlags.isEnabled(key, registry))
    }

    @Test
    fun nonBooleanDefaultIsOff() {
        assertFalse(FeatureFlags.isEnabled(key, """{"version":1,"flags":[{"key":"$key","default":1}]}"""))
        assertFalse(FeatureFlags.isEnabled(key, """{"version":1,"flags":[{"key":"$key","default":"true"}]}"""))
        // iOS는 항목 하나라도 해석하지 못하면 레지스트리 전체를 OFF로 본다.
        assertFalse(
            FeatureFlags.isEnabled(
                key,
                """{"version":1,"flags":[{"key":"$key","default":true},{"key":"other","default":"true"}]}""",
            ),
        )
    }

    @Test
    fun booleanDefaults() {
        assertTrue(FeatureFlags.isEnabled(key, """{"version":1,"flags":[{"key":"$key","default":true}]}"""))
        assertFalse(FeatureFlags.isEnabled(key, """{"version":1,"flags":[{"key":"$key","default":false}]}"""))
    }

    @Test
    fun wrongVersionIsOff() {
        assertFalse(FeatureFlags.isEnabled(key, """{"version":2,"flags":[{"key":"$key","default":true}]}"""))
        assertFalse(FeatureFlags.isEnabled(key, """{"flags":[{"key":"$key","default":true}]}"""))
    }

    @Test
    fun androidIgnoresIOSFlags() {
        val ios = """{"version":1,"flags":[{"key":"user_server_ai","default":true},{"key":"ios_core_flow","default":true}]}"""
        assertEquals(FeatureFlags(false, false, false), FeatureFlags.resolve(ios, emptyMap(), debug = true))
    }

    @Test
    fun onlyDebugAppliesLaunchOverrides() {
        val registry = """{"version":1,"flags":[{"key":"$key","default":false},{"key":"${FeatureFlags.SERVER_AI}","default":true}]}"""
        val overrides = mapOf(key to true, FeatureFlags.SERVER_AI to false, "user_server_ai" to true)

        assertEquals(FeatureFlags(true, false, false), FeatureFlags.resolve(registry, overrides, debug = true))
        assertEquals(FeatureFlags(false, true, false), FeatureFlags.resolve(registry, overrides, debug = false))
    }
}

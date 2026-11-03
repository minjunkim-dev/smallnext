package dev.smallnext.app

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.crashlytics.FirebaseCrashlytics

/** Firebase 공개 클라이언트 설정. iOS `FirebaseClientConfiguration`과 같은 형식 검사를 한다. */
data class FirebaseConfig(val appId: String, val senderId: String, val projectId: String, val apiKey: String) {
    /** 하나라도 비었거나 형식이 틀리면 null이다. 잘못된 프로젝트로 보내지 않는다. */
    fun options(): FirebaseOptions? {
        val app = Regex("1:([0-9]+):android:[0-9a-f]+").matchEntire(appId) ?: return null
        if (app.groupValues[1] != senderId ||
            !Regex("[a-z][a-z0-9-]{4,28}[a-z0-9]").matches(projectId) ||
            !Regex("AIza[A-Za-z0-9_-]{35}").matches(apiKey)
        ) return null
        return FirebaseOptions.Builder()
            .setApplicationId(appId)
            .setGcmSenderId(senderId)
            .setProjectId(projectId)
            .setApiKey(apiKey)
            .build()
    }

    companion object {
        val build = FirebaseConfig(
            BuildConfig.FIREBASE_APP_ID,
            BuildConfig.FIREBASE_SENDER_ID,
            BuildConfig.FIREBASE_PROJECT_ID,
            BuildConfig.FIREBASE_API_KEY,
        )
    }
}

object CrashReporting {
    const val TEST_CRASH = "crashlytics_test_crash"

    /** 플래그가 꺼져 있거나 설정이 잘못되면 Firebase를 초기화하지 않고 false를 반환한다. */
    fun start(context: Context, enabled: Boolean, launch: Intent? = null, config: FirebaseConfig = FirebaseConfig.build): Boolean {
        val options = (if (enabled) config.options() else null) ?: return false
        val app = FirebaseApp.getApps(context).firstOrNull { it.name == FirebaseApp.DEFAULT_APP_NAME }
            ?: FirebaseApp.initializeApp(context, options)
        if (app.options != options) return false
        app.setDataCollectionDefaultEnabled(false)
        FirebaseCrashlytics.getInstance().run {
            // true는 다음 OFF 실행에도 남는다. 이번 ON 실행에서만 보낸다.
            setCrashlyticsCollectionEnabled(false)
            sendUnsentReports()
        }
        // Release는 외부 앱이 넣은 extra Bundle을 풀지도 않는다.
        if (launch?.takeIf { BuildConfig.DEBUG }?.getBooleanExtra(TEST_CRASH, false) == true) {
            Handler(Looper.getMainLooper()).postDelayed({
                throw IllegalStateException("Smallnext Crashlytics synthetic validation")
            }, 3_000)
        }
        return true
    }
}

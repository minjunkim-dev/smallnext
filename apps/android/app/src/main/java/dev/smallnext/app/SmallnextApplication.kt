package dev.smallnext.app

import android.app.Application
import dev.smallnext.app.data.AppDatabase
import dev.smallnext.app.progress.ProgressFlow
import dev.smallnext.app.progress.defaultSuggestionProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async

class SmallnextApplication : Application() {
    val database: AppDatabase by lazy { AppDatabase.open(this) }

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /** `android_core_flow` 경로에서만 연다. 진행 흐름과 대기 요청은 Activity가 아니라 앱 수명에 묶는다. */
    val progressFlow: Deferred<ProgressFlow> by lazy {
        appScope.async { ProgressFlow.open(database, defaultSuggestionProvider(), appScope) }
    }
}

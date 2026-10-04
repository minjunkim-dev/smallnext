package dev.smallnext.app

import android.app.Application
import dev.smallnext.app.data.AppDatabase

class SmallnextApplication : Application() {
    val database: AppDatabase by lazy { AppDatabase.open(this) }
}

package dev.smallnext.app.progress

/** Release에는 Debug 고정 공급자가 없다. 서버 공급자 연결은 #358에서 한다. */
fun defaultSuggestionProvider(): ActionSuggestionProvider = UnavailableSuggestionProvider

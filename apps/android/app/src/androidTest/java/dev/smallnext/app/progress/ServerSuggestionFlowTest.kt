package dev.smallnext.app.progress

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.smallnext.app.data.AppDatabase
import java.net.SocketException
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

/** [ServerSuggestionProvider]를 진행 흐름에 넣어 가짜 전송으로 첫 행동을 받고, 전송 실패 뒤에도 진행이 남는지 확인한다. */
@RunWith(AndroidJUnit4::class)
class ServerSuggestionFlowTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val name = "smallnext-test-${UUID.randomUUID()}.sqlite"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val databases = mutableListOf<AppDatabase>()
    private val calls = AtomicInteger()

    @After
    fun tearDown() {
        scope.cancel()
        databases.forEach { it.close() }
        context.deleteDatabase(name)
    }

    /** 첫 호출은 행동을 받고, 이후 호출은 연결이 끊긴다. */
    private val transport = Interceptor { chain ->
        if (calls.incrementAndGet() > 1) throw SocketException("Connection reset")
        val body = Buffer().also { chain.request().body?.writeTo(it) }.readUtf8()
        val input = JsonParser.parseString(body).asJsonObject["input"].asJsonObject
        val proposal = JsonObject().apply {
            addProperty("status", "action")
            addProperty("action", "관련 메모 하나 열기")
            addProperty("completion_condition", "메모가 화면에 열려 있다")
            addProperty("estimated_minutes", 2.5)
            addProperty("reason", "바로 시작할 수 있다")
            add("remaining_work", input["remaining_work"])
            add("preserved_completed_ids", input["completed_ids"])
            addProperty("goal_completed", false)
            addProperty("current_action_completed", false)
        }
        val data = JsonObject().apply { addProperty("disposition", "accepted"); add("proposal", proposal) }.toString()
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK").body(data.toResponseBody()).build()
    }

    private suspend fun makeFlow() = ProgressFlow.open(
        AppDatabase.open(context, name).also(databases::add),
        goalPreparing(
            ServerSuggestionProvider.create("https://api.example.invalid", { "test-token" }, OkHttpClient.Builder().addInterceptor(transport).build()),
        ),
        scope,
    )

    @Test
    fun testServerProviderGivesFirstActionAndTransportFailureKeepsProgressWithoutRetry() = runBlocking {
        val flow = makeFlow()
        flow.prepareGoal(GoalInput("주간 보고서 쓰기"))
        flow.awaitSuggestion()
        flow.confirmGoal("주간 보고서 쓰기")
        flow.awaitSuggestion()
        val card = (flow.state.value.screen as ProgressScreen.CurrentAction).card
        assertEquals(ActionCard(card.id, "관련 메모 하나 열기", "메모가 화면에 열려 있다", 3), card)

        flow.complete(card.id)
        flow.awaitSuggestion()
        assertEquals(ProgressScreen.AwaitingNextAction(SuggestionProblem.Failure(SuggestionFailure.CONNECTION_LOST)), flow.state.value.screen)
        delay(200)
        assertEquals(2, calls.get())

        databases.forEach { it.close() }
        databases.clear()
        val reopened = makeFlow()
        assertEquals(ProgressScreen.AwaitingNextAction(SuggestionProblem.Failure(SuggestionFailure.CONNECTION_LOST)), reopened.state.value.screen)
        assertEquals("주간 보고서 쓰기", reopened.state.value.goal?.statement)
        val completions = databases.single().openHelper.readableDatabase.query("SELECT COUNT(*) FROM completion").use { it.moveToFirst(); it.getLong(0) }
        assertEquals(1L, completions)
        assertEquals(2, calls.get())
    }
}

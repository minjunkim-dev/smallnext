package dev.smallnext.app.progress

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.JsonPrimitive
import java.io.File
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * 서버 경로 계약을 OkHttp 인터셉터 가짜 전송으로 확인한다. 이름은 iOS `ServerSuggestionProviderTests`·`DevelopmentAITests`와 같다.
 * iOS에만 있는 계정 삭제(#360)와 `SuggestionTiming` 사례는 옮기지 않는다. 개발 경로 사례는 서버 공급자로 확인한다.
 */
class ServerSuggestionProviderTest {
    private class Sent(val request: Request, val body: ByteArray) {
        val input: JsonObject get() = JsonParser.parseString(body.toString(Charsets.UTF_8)).asJsonObject["input"].asJsonObject
    }

    /** iOS `DevelopmentTransport`와 같다. 처리기가 없으면 호출이 취소될 때까지 붙잡고 [stopped]를 기록한다. */
    private class FakeTransport : Interceptor {
        val requests = CopyOnWriteArrayList<Sent>()
        @Volatile var handler: ((Sent) -> Pair<Int, ByteArray>)? = null
        @Volatile var stopped = false

        override fun intercept(chain: Interceptor.Chain): Response {
            val body = Buffer().also { chain.request().body?.writeTo(it) }.readByteArray()
            val sent = Sent(chain.request(), body).also(requests::add)
            val handler = handler ?: run {
                while (!chain.call().isCanceled()) Thread.sleep(10)
                stopped = true
                throw IOException("Canceled")
            }
            val (code, data) = handler(sent)
            return Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(code).message("")
                .body(data.toResponseBody()).build()
        }
    }

    private val transport = FakeTransport()

    private fun provider(token: suspend () -> String = { "supabase-test-access-token" }) = ServerSuggestionProvider.create(
        "https://api.example.invalid", token, OkHttpClient.Builder().addInterceptor(transport).build(),
    )

    private fun request(kind: SuggestionKind = SuggestionKind.FIRST_ACTION, goal: String = "정리") = SuggestionRequest(kind, goal)

    private fun accepted(
        sent: Sent, status: String = "action", complete: Boolean = false, wrongScope: Boolean = false, blank: Boolean = false,
    ): ByteArray {
        val input = sent.input
        val proposal = JsonObject().apply {
            addProperty("status", status)
            addProperty("action", "펜 하나 옮기기")
            addProperty("completion_condition", if (blank) " " else "펜이 펜꽂이에 있다")
            addProperty("estimated_minutes", 1)
            addProperty("reason", "한 물건만 옮긴다")
            add("remaining_work", if (wrongScope) JsonArray().apply { add("다른 범위") } else input["remaining_work"])
            add("preserved_completed_ids", input["completed_ids"])
            addProperty("goal_completed", complete)
            addProperty("current_action_completed", complete)
        }
        return JsonObject().apply { addProperty("disposition", "accepted"); add("proposal", proposal) }.toString().toByteArray()
    }

    private suspend fun failure(block: suspend () -> Unit): SuggestionFailure? = try {
        block()
        null
    } catch (error: SuggestionException) {
        error.failure
    }

    private fun fixture(name: String): JsonObject {
        var dir: File? = File(System.getProperty("user.dir")!!).absoluteFile
        while (dir != null && !File(dir, "contracts/fixtures").isDirectory) dir = dir.parentFile
        return JsonParser.parseString(File(dir, "contracts/fixtures/$name").readText()).asJsonObject
    }

    private fun insufficientResponse() = fixture("insufficient-info.json")["response"].asJsonObject

    private fun insufficientReason() = insufficientResponse()["proposal"].asJsonObject["reason"].asString

    private val pen = ProposedAction("펜 하나 옮기기", "펜이 펜꽂이에 있다", 1)

    @Test
    fun testPlainHTTPOrCredentialURLNeverObtainsIdentity() = runBlocking {
        for (address in listOf(
            "http://api.example.invalid", "https://name:pass@api.example.invalid", "https://api.example.invalid?token=x",
            "https://api.example.invalid/v1", "https://api.example.invalid#x", "not a url",
        )) {
            val provider = ServerSuggestionProvider.create(address, { fail("invalid endpoint must not obtain identity"); "unused" })
            assertEquals(address, SuggestionFailure.UNAVAILABLE, failure { provider.suggest(request()) })
        }
        assertTrue(ServerSuggestionProvider.endpoint("https://api.example.invalid/"))
    }

    @Test
    fun testAuthTokenAndServerPathPreserveAllCandidateTypes() = runBlocking {
        for ((kind, status, expected) in listOf(
            Triple(SuggestionKind.FIRST_ACTION, "action", SuggestionCandidate.Action(pen)),
            Triple(SuggestionKind.SMALLER, "minimum", SuggestionCandidate.MinimalAction(pen)),
            Triple(SuggestionKind.GOAL_PREPARATION, "need_info", SuggestionCandidate.Question("펜 하나 옮기기")),
            Triple(SuggestionKind.GOAL_PREPARATION, "goal_summary", SuggestionCandidate.GoalSummary("펜이 펜꽂이에 있다")),
            Triple(SuggestionKind.REPLACEMENT, "no_action", SuggestionCandidate.NoAction),
        )) {
            transport.requests.clear()
            transport.handler = { 200 to accepted(it, status) }
            val candidate = provider().suggest(SuggestionRequest(kind, "책상 정리", stateKey = "2:3"))
            assertEquals(expected, candidate)
            assertEquals(1, transport.requests.size)
            val sent = transport.requests.single()
            assertEquals("POST", sent.request.method)
            assertEquals("/v1/suggestions", sent.request.url.encodedPath)
            assertEquals("Bearer supabase-test-access-token", sent.request.header("Authorization"))
            assertEquals("application/json", sent.request.body?.contentType().toString())
            assertEquals("2:3", JsonParser.parseString(sent.body.toString(Charsets.UTF_8)).asJsonObject["state_key"].asString)
        }
    }

    /** iOS는 `NoRedirect`와 `timeoutInterval = 160`이다. 주입한 클라이언트의 설정과 관계없이 같은 규칙을 쓴다. */
    @Test
    fun testTransportNeverRedirectsRetriesConnectionsAndTimesOutAt160Seconds() {
        val loose = OkHttpClient.Builder().followRedirects(true).retryOnConnectionFailure(true).build()
        val provider = ServerSuggestionProvider.create("https://api.example.invalid", { "token" }, loose) as ServerSuggestionProvider
        assertFalse(provider.client.followRedirects)
        assertFalse(provider.client.followSslRedirects)
        assertFalse(provider.client.retryOnConnectionFailure)
        assertEquals(160_000, provider.client.callTimeoutMillis)
        assertEquals(160_000, provider.client.readTimeoutMillis)
    }

    @Test
    fun testAuthenticationTransportAndServerFailuresNeverRetryAI() = runBlocking {
        for ((status, reason) in listOf(
            401 to SuggestionFailure.REJECTED, 403 to SuggestionFailure.REJECTED, 400 to SuggestionFailure.REJECTED,
            413 to SuggestionFailure.REJECTED, 429 to SuggestionFailure.BUDGET_LIMIT, 408 to SuggestionFailure.TIMED_OUT,
            504 to SuggestionFailure.TIMED_OUT, 503 to SuggestionFailure.FAILED, 409 to SuggestionFailure.UNAVAILABLE,
            302 to SuggestionFailure.FAILED,
        )) {
            transport.requests.clear()
            transport.handler = { status to ByteArray(0) }
            assertEquals("$status", reason, failure { provider().suggest(request()) })
            assertEquals(1, transport.requests.size)
        }
        transport.requests.clear()
        assertEquals(
            SuggestionFailure.UNAVAILABLE,
            failure { provider(token = { throw SuggestionException(SuggestionFailure.UNAVAILABLE) }).suggest(request()) },
        )
        assertTrue(transport.requests.isEmpty())
    }

    @Test
    fun testMalformedTokenIsNeverSent() = runBlocking {
        transport.handler = { 200 to accepted(it) }
        for (token in listOf("", "a b", "a\nb", "x".repeat(16 * 1024 + 1))) {
            assertEquals(SuggestionFailure.REJECTED, failure { provider(token = { token }).suggest(request()) })
        }
        assertTrue(transport.requests.isEmpty())
        provider(token = { "x".repeat(16 * 1024) }).suggest(request())
        assertEquals(1, transport.requests.size)
    }

    @Test
    fun testScopeMismatchBlankTextAndUnrepresentableCompletionClaimsCannotBecomeCandidates() = runBlocking {
        val request = request(SuggestionKind.GOAL_PREPARATION)
        for (case in listOf(
            listOf("action", false, true, false), listOf("need_info", true, false, false),
            listOf("goal_summary", true, false, false), listOf("no_action", false, false, true),
        )) {
            transport.handler = { accepted(it, case[0] as String, case[1] as Boolean, case[2] as Boolean, case[3] as Boolean).let { 200 to it } }
            assertEquals("${case[0]}", SuggestionFailure.REJECTED, failure { provider().suggest(request) })
        }
    }

    @Test
    fun testActionCompletionClaimReachesCandidatePolicy() = runBlocking {
        val request = request()
        transport.handler = { 200 to accepted(it, complete = true) }
        val candidate = provider().suggest(request)
        assertTrue((candidate as SuggestionCandidate.Action).action.marksGoalComplete)
        assertNull(CandidatePolicy.accept(candidate, request))
    }

    @Test
    fun testCancellationDuringIdentityPreparationNeverSendsAIRequest() = runBlocking {
        val client = provider(token = { delay(10_000); "unused" })
        val pending = async(Dispatchers.Default) { client.suggest(request()) }
        delay(50)
        pending.cancel()
        try {
            pending.await()
            fail("must cancel")
        } catch (_: CancellationException) {
        }
        assertTrue(transport.requests.isEmpty())
    }

    // DevelopmentAITests

    @Test
    fun testHTTPProposalPreservesSplitScopeCompletedIDsAndCompletionFlags() = runBlocking {
        transport.handler = { 200 to accepted(it, complete = true) }
        val request = SuggestionRequest(
            SuggestionKind.SMALLER, "책상 정리", currentAction = ProposedAction("펜 정리", "정리됨", 5), completedTasks = listOf("종이 정리"),
            stateKey = "1:2", remainingTasks = listOf("책상 왼쪽 정리", "펜 정리"), completedActionIds = listOf("7"),
            splitSources = listOf("책상 왼쪽 정리"), blocker = "무엇부터 할지 모른다",
        )
        val action = (provider().suggest(request) as SuggestionCandidate.Action).action
        assertTrue(action.marksGoalComplete)
        assertTrue(action.marksCurrentActionComplete)
        val input = transport.requests.single().input
        assertEquals(listOf("책상 정리", "책상 왼쪽 정리", "펜 정리"), input.strings("remaining_work"))
        assertEquals(listOf("7"), input.strings("completed_ids"))
        assertEquals(request.blocker, input["current_blocker"].asString)
        assertEquals(listOf("책상 왼쪽 정리", "펜 정리"), input["previous_proposals"].asJsonArray.map { it.asJsonObject["action"].asString })
    }

    /** iOS `Input`의 사실 순서·접두사, 종류별 요청 문장, 기본 15분을 그대로 보낸다. 서버 `AiInput`의 필드만 쓴다. */
    @Test
    fun testRequestBodyFollowsSharedInputRules() = runBlocking {
        transport.handler = { 200 to accepted(it) }
        val context = GoalContext(
            deadline = "금요일", currentState = "초안 없음", materialLinks = listOf("https://example.com/a?b=c&d=<e>"),
            materialExcerpt = "발췌", answers = listOf(GoalAnswer("어디", "책상")),
        )
        val request = SuggestionRequest(
            SuggestionKind.NEXT_ACTION, "보고서", completedTasks = listOf("메모 열기"), deferredTasks = listOf("표 그리기"),
            context = context, completionCriteria = "보고서 제출", actionAnswers = listOf(GoalAnswer("막힘", "자료")), supplementalText = "보충",
        )
        provider().suggest(request)
        val input = transport.requests.single().input
        assertEquals(
            setOf(
                "goal", "current_blocker", "user_request", "available", "unknown", "available_minutes", "knowledge", "energy",
                "remaining_work", "completed_ids", "previous_proposals", "request_kind",
            ),
            input.keySet(),
        )
        assertEquals(
            listOf(
                "확정 완료 조건: 보고서 제출", "현재 상태: 초안 없음", "기한: 금요일", "사용자가 선택한 자료 발췌: 발췌",
                "사용자가 확인해 저장한 보충 내용(외부 검증 미확인): 보충", "자료 링크(본문을 읽지 않음): https://example.com/a?b=c&d=<e>",
                "이미 답한 질문: 어디 / 답: 책상", "행동 요청에서 이미 답한 질문: 막힘 / 답: 자료", "이미 완료한 행동: 메모 열기",
                "보류한 행동(재제안 금지): 표 그리기",
            ),
            input.strings("available"),
        )
        assertEquals(15.0, input["available_minutes"].asDouble, 0.0)
        assertEquals("", input["current_blocker"].asString)
        assertEquals(listOf("보고서 제출"), input.strings("remaining_work"))
        assertEquals("next_action", input["request_kind"].asString)
        assertEquals("사용자가 제공한 정보 외에는 모름", input["knowledge"].asString)
        assertEquals("모름", input["energy"].asString)
        assertTrue(input["previous_proposals"].asJsonArray.isEmpty)
        for ((kind, text) in listOf(
            SuggestionKind.GOAL_PREPARATION to "최종 목표의 관찰 가능한 완료 조건을 제안한다. 사용자가 확인하기 전에는 확정하지 않는다.",
            SuggestionKind.FIRST_ACTION to "지금 시작할 첫 행동 하나를 제안한다.",
            SuggestionKind.NEXT_ACTION to "완료한 행동을 반복하지 않고 남은 범위의 다음 행동 하나를 제안한다.",
            SuggestionKind.SMALLER to "현재 행동을 실질적으로 줄인다. 반복 막힘이면 알려진 답을 다시 묻지 않고 첫 막힘 한 가지를 확인한다.",
            SuggestionKind.REPLACEMENT to "보류한 행동과 다른 준비된 행동 하나를 제안한다. 없으면 no_action을 반환한다.",
        )) {
            transport.requests.clear()
            runCatching { provider().suggest(SuggestionRequest(kind, "정리", context = GoalContext(availableMinutes = 40))) }
            val sent = transport.requests.single().input
            assertEquals(text, sent["user_request"].asString)
            assertEquals(40.0, sent["available_minutes"].asDouble, 0.0)
            assertTrue(sent["available"].asJsonArray.isEmpty)
        }
    }

    @Test
    fun testTransportFailuresMapWithoutAutomaticRetry() = runBlocking {
        val request = SuggestionRequest(SuggestionKind.FIRST_ACTION, "정리", stateKey = "1:0")
        for ((error, expected) in listOf(
            UnknownHostException() to SuggestionFailure.CONNECTION_LOST, java.net.ConnectException() to SuggestionFailure.CONNECTION_LOST,
            java.net.SocketException("Connection reset") to SuggestionFailure.CONNECTION_LOST,
            SocketTimeoutException() to SuggestionFailure.TIMED_OUT, javax.net.ssl.SSLHandshakeException("x") to SuggestionFailure.FAILED,
        )) {
            transport.requests.clear()
            transport.handler = { throw error }
            assertEquals("$error", expected, failure { provider().suggest(request) })
            assertEquals(1, transport.requests.size)
        }
        for ((value, expected) in listOf(
            "rejected" to SuggestionFailure.REJECTED, "invalid_input" to SuggestionFailure.REJECTED,
            "invalid_proposal" to SuggestionFailure.REJECTED, "uncertain" to SuggestionFailure.UNDECIDABLE,
            "budget_limit" to SuggestionFailure.BUDGET_LIMIT, "timed_out" to SuggestionFailure.TIMED_OUT,
            "connection_lost" to SuggestionFailure.CONNECTION_LOST, "disabled" to SuggestionFailure.UNAVAILABLE,
            "busy" to SuggestionFailure.UNAVAILABLE, "superseded" to SuggestionFailure.UNAVAILABLE, "future" to SuggestionFailure.FAILED,
        )) {
            transport.requests.clear()
            transport.handler = { 200 to "{\"disposition\":\"$value\"}".toByteArray() }
            assertEquals(value, expected, failure { provider().suggest(request) })
            assertEquals(1, transport.requests.size)
        }
        transport.handler = { 200 to "{\"disposition\":\"accepted\"}".toByteArray() }
        assertEquals(SuggestionFailure.REJECTED, failure { provider().suggest(request) })
        for (body in listOf("", "not json", "{\"disposition\":1}", "{\"disposition\":\"accepted\",\"proposal\":{}}", "{} {}")) {
            transport.handler = { 200 to body.toByteArray() }
            assertEquals(body, SuggestionFailure.FAILED, failure { provider().suggest(request) })
        }
    }

    @Test
    fun testResponseOverLimitIsNotDecoded() = runBlocking {
        val request = request()
        transport.handler = { sent ->
            val body = JsonParser.parseString(accepted(sent).toString(Charsets.UTF_8)).asJsonObject
            body.addProperty("padding", "")
            val size = body.toString().toByteArray().size
            body.addProperty("padding", "x".repeat(128 * 1024 - size))
            200 to body.toString().toByteArray()
        }
        assertEquals(SuggestionCandidate.Action(pen), provider().suggest(request))
        val exact = transport.handler!!
        transport.handler = { sent -> exact(sent).let { (code, data) -> code to data.copyOf(data.size + 1).also { it[data.size] = ' '.code.toByte() } } }
        assertEquals(SuggestionFailure.FAILED, failure { provider().suggest(request) })
    }

    @Test
    fun testCancellationStopsHTTPTransport() = runBlocking {
        transport.handler = null
        val task = async(Dispatchers.Default) { provider().suggest(SuggestionRequest(SuggestionKind.FIRST_ACTION, "정리", stateKey = "1:0")) }
        withTimeout(2_000) { while (transport.requests.isEmpty()) delay(10) }
        assertEquals(1, transport.requests.size)
        task.cancel()
        try {
            task.await()
            fail("must cancel")
        } catch (_: CancellationException) {
        }
        withTimeout(2_000) { while (!transport.stopped) delay(10) }
        assertEquals(1, transport.requests.size)
    }

    @Test
    fun testGoalSummaryQuestionAndNoAlternativeKeepTheirCandidateTypes() = runBlocking {
        for ((kind, status, expected) in listOf(
            Triple(SuggestionKind.GOAL_PREPARATION, "goal_summary", SuggestionCandidate.GoalSummary("펜이 펜꽂이에 있다")),
            Triple(SuggestionKind.GOAL_PREPARATION, "need_info", SuggestionCandidate.Question("펜 하나 옮기기")),
            Triple(SuggestionKind.REPLACEMENT, "no_action", SuggestionCandidate.NoAction),
        )) {
            transport.handler = { 200 to accepted(it, status) }
            assertEquals(expected, provider().suggest(SuggestionRequest(kind, "펜 정리", stateKey = "1:0")))
        }
    }

    @Test
    fun testSharedInsufficientInfoIsAValidTransportResponse() = runBlocking {
        val response = insufficientResponse().toString().toByteArray()
        transport.handler = { 200 to response }
        for (kind in listOf(SuggestionKind.FIRST_ACTION, SuggestionKind.NEXT_ACTION, SuggestionKind.SMALLER, SuggestionKind.REPLACEMENT)) {
            val request = request(kind, "과거 경력 사실 정리")
            val candidate = provider().suggest(request)
            assertEquals(SuggestionCandidate.InsufficientInfo(insufficientReason()), candidate)
            assertNotNull(CandidatePolicy.accept(candidate, request))
        }
        assertEquals(4, transport.requests.size)
    }

    @Test
    fun testInsufficientInfoRejectsMalformedFieldsAndGoalPreparation() = runBlocking {
        for ((field, value) in listOf<Pair<String, JsonElement>>(
            "action" to JsonPrimitive("가짜 행동"), "completion_condition" to JsonPrimitive(" "), "estimated_minutes" to JsonPrimitive(1),
            "reason" to JsonPrimitive(" "), "goal_completed" to JsonPrimitive(true), "current_action_completed" to JsonPrimitive(true),
            "preserved_completed_ids" to JsonArray().apply { add("new") }, "remaining_work" to JsonArray().apply { add("changed") },
            "status" to JsonPrimitive("future_status"),
        )) {
            val response = insufficientResponse().apply { this["proposal"].asJsonObject.add(field, value) }
            transport.requests.clear()
            transport.handler = { 200 to response.toString().toByteArray() }
            assertEquals(field, SuggestionFailure.REJECTED, failure { provider().suggest(request(goal = "과거 경력 사실 정리")) })
            assertEquals(1, transport.requests.size)
        }
        transport.handler = { 200 to insufficientResponse().toString().toByteArray() }
        assertEquals(
            SuggestionFailure.REJECTED,
            failure { provider().suggest(request(SuggestionKind.GOAL_PREPARATION, "과거 경력 사실 정리")) },
        )
    }

    @Test
    fun testFingerprintNormalizesOnlyActualInputAndPreservesOrder() {
        val original = SuggestionRequest(
            SuggestionKind.SMALLER, "  정리\r\n계속  ", currentAction = ProposedAction("한 부분", "결과", 2), completedTasks = listOf("하나", "둘"),
            stateKey = "1:2", remainingTasks = listOf("첫째", "둘째"), completedActionIds = listOf("7", "3"),
        )
        fun fingerprint(request: SuggestionRequest) = ServerSuggestionProvider.inputFingerprint(request)
        val value = fingerprint(original)
        assertEquals(64, value.length)
        assertEquals(value, fingerprint(original.copy(goal = "정리\n계속", stateKey = "different-goal:999")))
        assertEquals(value, fingerprint(original.copy(goal = "정리\r계속")))
        assertEquals("  정리\r\n계속  ", original.goal)
        assertEquals(value, fingerprint(original.copy(supplementalText = "  ")))
        assertEquals(fingerprint(original.copy(supplementalText = "보충")), fingerprint(original.copy(supplementalText = " 보충\r\n")))
        assertNotEquals(value, fingerprint(original.copy(remainingTasks = original.remainingTasks.reversed())))
        assertNotEquals(value, fingerprint(original.copy(completedActionIds = original.completedActionIds.reversed())))
        assertNotEquals(value, fingerprint(original.copy(kind = SuggestionKind.FIRST_ACTION)))
        assertNotEquals(value, fingerprint(original.copy(context = GoalContext(answers = listOf(GoalAnswer("어디", "모름"))))))
        assertNotEquals(value, fingerprint(original.copy(context = GoalContext(materialExcerpt = "사용자가 선택한 원문"))))
        assertNotEquals(value, fingerprint(original.copy(currentAction = original.currentAction!!.copy(doneWhen = "다른 결과"))))
    }

    @Test
    fun testOversizedBlockerIsNotTransmitted() = runBlocking {
        val request = SuggestionRequest(SuggestionKind.FIRST_ACTION, "정리", blocker = "가".repeat(683), stateKey = "1:0")
        assertEquals(SuggestionFailure.REJECTED, failure { provider().suggest(request) })
        assertTrue(transport.requests.isEmpty())
    }

    @Test
    fun testConfirmedSupplementalRespectsWholeHTTPBodyAndBlockerByteLimits() = runBlocking {
        val provider = provider()
        transport.handler = { 200 to accepted(it) }
        var request = SuggestionRequest(
            SuggestionKind.FIRST_ACTION, "정리", remainingTasks = listOf("남은 원문"), completedActionIds = listOf("7", "3"), supplementalText = "x",
        )
        provider.suggest(request)
        val baseline = transport.requests.last().body.size
        request = request.copy(supplementalText = "x".repeat(32 * 1024 - baseline + 1))
        provider.suggest(request)
        assertEquals(32 * 1024, transport.requests.last().body.size)
        assertEquals(SuggestionFailure.REJECTED, failure { provider.suggest(request.copy(supplementalText = request.supplementalText + "x")) })
        assertEquals(2, transport.requests.size)
        request = request.copy(supplementalText = "새 정보", blocker = "x".repeat(2048))
        provider.suggest(request)
        val input = transport.requests.last().input
        assertEquals(request.blocker, input["current_blocker"].asString)
        assertEquals(listOf("정리", "남은 원문"), input.strings("remaining_work"))
        assertEquals(listOf("7", "3"), input.strings("completed_ids"))
        assertEquals(SuggestionFailure.REJECTED, failure { provider.suggest(request.copy(blocker = request.blocker + "x")) })
        assertEquals(3, transport.requests.size)
    }

    // contracts/fixtures/suggestion-compact.json: Rust `compact_contract_matches_shared_fixture`가 같은 파일을 고정한다.

    /** 서버가 요청 종류별로 허용하는 상태만 이 공급자와 [CandidatePolicy]를 함께 통과한다. */
    @Test
    fun testCompactStatusesMatchWhatTheAppAcceptsPerRequestKind() = runBlocking {
        val statuses = fixture("suggestion-compact.json")["statuses"].asJsonObject
        val all = listOf("action", "minimum", "need_info", "goal_summary", "no_action", "insufficient_info")
        for (kind in SuggestionKind.entries) {
            val allowed = statuses.strings(kind.raw).toSet()
            assertTrue(kind.raw, allowed.isNotEmpty() && all.containsAll(allowed))
            for (status in all) {
                val request = request(kind)
                transport.handler = {
                    if (status == "insufficient_info") {
                        val response = insufficientResponse()
                        response["proposal"].asJsonObject.add("remaining_work", it.input["remaining_work"])
                        200 to response.toString().toByteArray()
                    } else {
                        200 to accepted(it, status)
                    }
                }
                val accepted = try {
                    CandidatePolicy.accept(provider().suggest(request), request) != null
                } catch (_: SuggestionException) {
                    false
                }
                assertEquals("${kind.raw} $status", status in allowed, accepted)
            }
        }
    }

    /** 검사 사례의 후보를 원래 요청의 범위로 보내면, 허용 상태이고 범위·완료 ID를 보존하고 완료 표시가 없을 때만 받는다. */
    @Test
    fun testCompactCheckCandidatesKeepScopeAndAllowedStatus() = runBlocking {
        val compact = fixture("suggestion-compact.json")
        val statuses = compact["statuses"].asJsonObject
        var checked = 0
        for (case in compact["cases"].asJsonArray.map { it.asJsonObject }.filter { it["role"].asString == "check" }) {
            val payload = case["payload"].asJsonObject
            val original = payload["original_request"].asJsonObject
            val kind = SuggestionKind.of(original["request_kind"].takeUnless { it.isJsonNull }?.asString) ?: continue
            val remaining = original.strings("remaining_work")
            val request = SuggestionRequest(
                kind, remaining.first(), remainingTasks = remaining.drop(1), completedActionIds = original.strings("completed_ids"),
            )
            val candidate = payload["candidate"].asJsonObject.deepCopy().apply {
                if (!has("goal_completed")) addProperty("goal_completed", false)
                if (!has("current_action_completed")) addProperty("current_action_completed", false)
            }
            transport.handler = {
                200 to JsonObject().apply { addProperty("disposition", "accepted"); add("proposal", candidate) }.toString().toByteArray()
            }
            val expected = candidate["status"].asString in statuses.strings(kind.raw) &&
                candidate.strings("remaining_work") == remaining && candidate.strings("preserved_completed_ids") == request.completedActionIds &&
                !candidate["goal_completed"].asBoolean && !candidate["current_action_completed"].asBoolean
            val accepted = try {
                CandidatePolicy.accept(provider().suggest(request), request) != null
            } catch (_: SuggestionException) {
                false
            }
            assertEquals(case["prompt"].asString + " " + kind.raw, expected, accepted)
            checked++
        }
        assertTrue(checked >= 4)
    }

    private fun JsonObject.strings(key: String) = getAsJsonArray(key).map { it.asString }
}

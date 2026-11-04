package dev.smallnext.app.progress

import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.google.gson.JsonPrimitive
import com.google.gson.Strictness
import com.google.gson.stream.JsonReader
import com.google.gson.stream.JsonToken
import java.io.IOException
import java.io.InterruptedIOException
import java.net.SocketException
import java.net.URI
import java.net.UnknownHostException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.math.ceil
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Authenticator
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

/**
 * 사용자 서버의 `POST /v1/suggestions` 공급자다. iOS `HTTPActionSuggestionProvider.server`와 같은 계약이다.
 * 응답의 wire 계약만 검사한다. 요청 종류와 후보의 호환은 [CandidatePolicy]가 판단한다.
 * 리다이렉트·연결 실패 재시도·401 뒤 재전송을 하지 않는다. 원문·토큰을 로그에 남기지 않는다.
 */
class ServerSuggestionProvider private constructor(
    private val url: HttpUrl,
    private val token: suspend () -> String,
    client: OkHttpClient,
) : ActionSuggestionProvider {
    internal val client = client.newBuilder()
        .followRedirects(false)
        .followSslRedirects(false)
        .retryOnConnectionFailure(false)
        .callTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .authenticator(Authenticator.NONE)
        .proxyAuthenticator(Authenticator.NONE)
        // OkHttp는 503 `Retry-After: 0`·421에도 같은 요청을 다시 보낸다. AI 요청은 호출마다 한 번만 보낸다.
        .addNetworkInterceptor { chain ->
            if (chain.request().tag(AtomicBoolean::class.java)?.getAndSet(true) == true) throw IOException("resend blocked")
            chain.proceed(chain.request())
        }
        .build()

    override suspend fun suggest(request: SuggestionRequest): SuggestionCandidate {
        currentCoroutineContext().ensureActive()
        val input = Input(request)
        val bytes = requestBody(request)
        val value = token()
        if (!validToken(value)) throw SuggestionException(SuggestionFailure.REJECTED)
        currentCoroutineContext().ensureActive()
        val http = Request.Builder()
            .url(url)
            .post(bytes.toRequestBody(JSON))
            .header("Authorization", "Bearer $value")
            .tag(AtomicBoolean::class.java, AtomicBoolean())
            .build()
        val (status, data) = try {
            client.newCall(http).await()
        } catch (error: IOException) {
            currentCoroutineContext().ensureActive()
            throw SuggestionException(
                when (error) {
                    // 호출 시간 제한은 InterruptedIOException("timeout"), 읽기 시간 제한은 SocketTimeoutException이다.
                    is InterruptedIOException -> SuggestionFailure.TIMED_OUT
                    is UnknownHostException, is SocketException -> SuggestionFailure.CONNECTION_LOST
                    else -> SuggestionFailure.FAILED
                },
            )
        }
        currentCoroutineContext().ensureActive()
        when (status) {
            200 -> Unit
            401, 403, 400, 413 -> throw SuggestionException(SuggestionFailure.REJECTED)
            429 -> throw SuggestionException(SuggestionFailure.BUDGET_LIMIT)
            408, 504 -> throw SuggestionException(SuggestionFailure.TIMED_OUT)
            409 -> throw SuggestionException(SuggestionFailure.UNAVAILABLE)
            else -> throw SuggestionException(SuggestionFailure.FAILED)
        }
        val result = data?.let(::decode) ?: throw SuggestionException(SuggestionFailure.FAILED)
        when (result.disposition) {
            "accepted" -> Unit
            "rejected", "invalid_input", "invalid_proposal" -> throw SuggestionException(SuggestionFailure.REJECTED)
            "uncertain" -> throw SuggestionException(SuggestionFailure.UNDECIDABLE)
            "timed_out" -> throw SuggestionException(SuggestionFailure.TIMED_OUT)
            "budget_limit" -> throw SuggestionException(SuggestionFailure.BUDGET_LIMIT)
            "connection_lost" -> throw SuggestionException(SuggestionFailure.CONNECTION_LOST)
            "disabled", "busy", "superseded" -> throw SuggestionException(SuggestionFailure.UNAVAILABLE)
            else -> throw SuggestionException(SuggestionFailure.FAILED)
        }
        return candidate(result.proposal, input, request.kind) ?: throw SuggestionException(SuggestionFailure.REJECTED)
    }

    /** 범위가 바뀌었거나 담을 수 없는 표시가 있는 응답은 null이다. iOS `suggest`의 응답 검사와 같은 순서다. */
    private fun candidate(proposal: Proposal?, input: Input, kind: SuggestionKind): SuggestionCandidate? {
        proposal ?: return null
        val minutes = proposal.estimated_minutes
        if (proposal.remaining_work != input.remaining_work || proposal.preserved_completed_ids != input.completed_ids ||
            !minutes.isFinite() || minutes < 0 || minutes >= Int.MAX_VALUE || minutes > input.available_minutes ||
            proposal.reason.isBlank()
        ) {
            return null
        }
        if (proposal.status == "insufficient_info") {
            if (kind == SuggestionKind.GOAL_PREPARATION || proposal.action.isNotEmpty() || proposal.completion_condition.isNotEmpty() ||
                minutes != 0.0 || proposal.goal_completed || proposal.current_action_completed
            ) {
                return null
            }
            return SuggestionCandidate.InsufficientInfo(proposal.reason)
        }
        if (proposal.action.isBlank() || proposal.completion_condition.isBlank()) return null
        val action = ProposedAction(
            task = proposal.action,
            doneWhen = proposal.completion_condition,
            estimatedMinutes = ceil(minutes).toInt(),
            marksGoalComplete = proposal.goal_completed,
            marksCurrentActionComplete = proposal.current_action_completed,
        )
        when (proposal.status) {
            "action" -> return SuggestionCandidate.Action(action)
            "minimum" -> return SuggestionCandidate.MinimalAction(action)
        }
        // 아래 후보 종류는 완료 표시를 담지 못한다. 표시가 있으면 여기서 거부한다.
        if (proposal.goal_completed || proposal.current_action_completed) return null
        return when (proposal.status) {
            "need_info" -> SuggestionCandidate.Question(proposal.action)
            "goal_summary" -> SuggestionCandidate.GoalSummary(proposal.completion_condition)
            "no_action" -> SuggestionCandidate.NoAction
            else -> null
        }
    }

    companion object {
        internal const val TIMEOUT_SECONDS = 160L
        private const val BLOCKER_LIMIT = 2 * 1024
        private const val BODY_LIMIT = 32 * 1024
        private const val RESPONSE_LIMIT = 128 * 1024L
        private const val TOKEN_LIMIT = 16 * 1024
        private val JSON = "application/json".toMediaType()
        private val gson = GsonBuilder().disableHtmlEscaping().create()

        /** https 서버 주소만 받는다. 주소가 맞지 않으면 [token]을 부르지 않는 공급자를 돌려준다. */
        fun create(baseUrl: String, token: suspend () -> String, client: OkHttpClient = OkHttpClient()): ActionSuggestionProvider {
            val url = baseUrl.takeIf(::endpoint)?.toHttpUrlOrNull()?.resolve("v1/suggestions") ?: return UnavailableSuggestionProvider
            return ServerSuggestionProvider(url, token, client)
        }

        /** 경로·자격 증명·query·fragment 없는 https 주소만 받는다. iOS `endpoint(_:schemes:)`와 같다. */
        fun endpoint(address: String): Boolean = try {
            val uri = URI(address)
            uri.scheme?.lowercase() == "https" && !uri.host.isNullOrEmpty() && uri.rawUserInfo == null &&
                uri.rawQuery == null && uri.rawFragment == null && (uri.rawPath.isNullOrEmpty() || uri.rawPath == "/")
        } catch (_: Exception) {
            false
        }

        /** iOS는 공백만 막는다. OkHttp 헤더는 출력 가능한 ASCII만 받으므로 그 밖의 문자도 전송 전에 거절한다. */
        private fun validToken(value: String) =
            value.isNotEmpty() && value.length <= TOKEN_LIMIT && value.all { it in '!'..'~' }

        /** 답을 확정하기 전에도 실제 송신할 본문과 같은 상한을 검사한다. */
        internal fun requestBody(request: SuggestionRequest): ByteArray {
            if ((request.blocker?.toByteArray()?.size ?: 0) > BLOCKER_LIMIT) throw SuggestionException(SuggestionFailure.REJECTED)
            val input = Input(request)
            if (gson.toJson(input).toByteArray().size > BODY_LIMIT) throw SuggestionException(SuggestionFailure.REJECTED)
            val bytes = gson.toJson(Payload(request.stateKey, input)).toByteArray()
            if (bytes.size > BODY_LIMIT) throw SuggestionException(SuggestionFailure.REJECTED)
            return bytes
        }

        /** 송신할 실제 입력만 정규화한다. 원문·배열 순서는 보존하고 요청 키는 제외한다. iOS `inputFingerprint`와 같은 규칙이다. */
        internal fun inputFingerprint(request: SuggestionRequest): String {
            fun normalizedText(text: String) = text.replace("\r\n", "\n").replace("\r", "\n").trim()
            fun normalized(value: JsonElement): JsonElement = when {
                value is JsonPrimitive && value.isString -> JsonPrimitive(normalizedText(value.asString))
                value is JsonArray -> JsonArray().apply { value.forEach { add(normalized(it)) } }
                value is JsonObject -> JsonObject().apply { value.keySet().sorted().forEach { add(it, normalized(value[it])) } }
                else -> value
            }
            // 설명 접두사를 붙이기 전에 보충 본문의 바깥 공백을 정규화한다. 송신 원문은 바꾸지 않는다.
            val input = Input(request.copy(supplementalText = normalizedText(request.supplementalText)))
            val bytes = gson.toJson(normalized(gson.toJsonTree(input))).toByteArray()
            return MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        }

        /** 형식이 맞지 않으면 null이다. `proposal`이 없거나 null이면 [Result.proposal]만 null이다. */
        private fun decode(data: ByteArray): Result? = try {
            val reader = JsonReader(data.toString(Charsets.UTF_8).reader()).apply { strictness = Strictness.STRICT }
            val root = JsonParser.parseReader(reader).asJsonObject
            check(reader.peek() == JsonToken.END_DOCUMENT)
            val proposal = root["proposal"]?.takeUnless { it.isJsonNull }?.asJsonObject?.let { p ->
                Proposal(
                    status = p.string("status"),
                    action = p.string("action"),
                    completion_condition = p.string("completion_condition"),
                    estimated_minutes = p.primitive("estimated_minutes").also { check(it.isNumber) }.asDouble,
                    reason = p.string("reason"),
                    remaining_work = p.strings("remaining_work"),
                    goal_completed = p.boolean("goal_completed"),
                    current_action_completed = p.boolean("current_action_completed"),
                    preserved_completed_ids = p.strings("preserved_completed_ids"),
                )
            }
            Result(root.string("disposition"), proposal)
        } catch (_: Exception) {
            null
        }

        private fun JsonObject.primitive(key: String) = getAsJsonPrimitive(key) ?: error(key)
        private fun JsonObject.string(key: String) = primitive(key).also { check(it.isString) }.asString
        private fun JsonObject.boolean(key: String) = primitive(key).also { check(it.isBoolean) }.asBoolean
        private fun JsonObject.strings(key: String) = getAsJsonArray(key).map { it.asJsonPrimitive.also { p -> check(p.isString) }.asString }
    }

    /** 응답 본문은 [RESPONSE_LIMIT]까지만 읽는다. 넘으면 본문을 null로 돌려준다. 취소하면 HTTP 호출을 끝낸다. */
    private suspend fun Call.await(): Pair<Int, ByteArray?> = suspendCancellableCoroutine { continuation ->
        continuation.invokeOnCancellation { cancel() }
        enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) = continuation.resumeWithException(e)

            override fun onResponse(call: Call, response: Response) {
                val result = try {
                    response.use {
                        val source = it.body.source()
                        val data = if (it.code != 200 || source.request(RESPONSE_LIMIT + 1)) null else source.buffer.readByteArray()
                        it.code to data
                    }
                } catch (e: IOException) {
                    return continuation.resumeWithException(e)
                }
                continuation.resume(result)
            }
        })
    }

    private class Payload(val state_key: String, val input: Input)

    @Suppress("PropertyName")
    private class Input(request: SuggestionRequest) {
        val goal = request.goal
        val current_blocker = request.blocker ?: ""
        val user_request = when (request.kind) {
            SuggestionKind.GOAL_PREPARATION -> "최종 목표의 관찰 가능한 완료 조건을 제안한다. 사용자가 확인하기 전에는 확정하지 않는다."
            SuggestionKind.FIRST_ACTION -> "지금 시작할 첫 행동 하나를 제안한다."
            SuggestionKind.NEXT_ACTION -> "완료한 행동을 반복하지 않고 남은 범위의 다음 행동 하나를 제안한다."
            SuggestionKind.SMALLER -> "현재 행동을 실질적으로 줄인다. 반복 막힘이면 알려진 답을 다시 묻지 않고 첫 막힘 한 가지를 확인한다."
            SuggestionKind.REPLACEMENT -> "보류한 행동과 다른 준비된 행동 하나를 제안한다. 없으면 no_action을 반환한다."
        }
        val available = buildList {
            val context = request.context
            request.completionCriteria?.let { add("확정 완료 조건: $it") }
            context.currentState?.let { add("현재 상태: $it") }
            context.deadline?.let { add("기한: $it") }
            context.materialExcerpt?.let { add("사용자가 선택한 자료 발췌: $it") }
            if (request.supplementalText.isNotBlank()) add("사용자가 확인해 저장한 보충 내용(외부 검증 미확인): ${request.supplementalText}")
            context.materialLinks.forEach { add("자료 링크(본문을 읽지 않음): $it") }
            context.answers.forEach { add("이미 답한 질문: ${it.question} / 답: ${it.answer}") }
            request.actionAnswers.forEach { add("행동 요청에서 이미 답한 질문: ${it.question} / 답: ${it.answer}") }
            request.completedTasks.forEach { add("이미 완료한 행동: $it") }
            request.deferredTasks.forEach { add("보류한 행동(재제안 금지): $it") }
        }
        val unknown = emptyList<String>()
        val available_minutes = (request.context.availableMinutes ?: 15).toDouble()
        val knowledge = "사용자가 제공한 정보 외에는 모름"
        val energy = "모름"
        val remaining_work = listOf(request.completionCriteria ?: request.goal) + request.remainingTasks
        val completed_ids = request.completedActionIds
        val previous_proposals = request.splitSources.map {
            Proposal("action", it, "원본 범위를 아직 완료하지 않음", 0.0, "미완료 분할 원본", remaining_work, false, false, completed_ids)
        } + listOfNotNull(
            request.currentAction?.takeIf { request.kind == SuggestionKind.SMALLER }?.let {
                Proposal("action", it.task, it.doneWhen, it.estimatedMinutes.toDouble(), "현재 미완료 행동", remaining_work, false, false, completed_ids)
            },
        )
        val request_kind = request.kind.raw
    }

    private class Result(val disposition: String, val proposal: Proposal?)

    @Suppress("PropertyName")
    private data class Proposal(
        val status: String,
        val action: String,
        val completion_condition: String,
        val estimated_minutes: Double,
        val reason: String,
        val remaining_work: List<String>,
        val goal_completed: Boolean,
        val current_action_completed: Boolean,
        val preserved_completed_ids: List<String>,
    )
}

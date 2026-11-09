// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.io.IOException
import java.util.concurrent.TimeUnit

val TrackerJson = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
    explicitNulls = true
    coerceInputValues = true
}

/** Normalises what the user typed ("casa.local:8000") into a base URL ending with "/". */
fun normalizeServerUrl(input: String): HttpUrl? {
    var s = input.trim()
    if (s.isEmpty()) return null
    if (!s.startsWith("http://", ignoreCase = true) && !s.startsWith("https://", ignoreCase = true)) {
        s = "https://$s"
    }
    val url = s.toHttpUrlOrNull() ?: return null
    val path = url.encodedPath.let { if (it.endsWith("/")) it else "$it/" }
    return url.newBuilder().encodedPath(path).query(null).fragment(null).build()
}

/**
 * Builds the HTTP stack for one server. [tokenProvider] supplies the bearer
 * token; [onUnauthorized] is called when the server rejects it (expired or
 * revoked), so the app can return to the login screen.
 */
class ApiClient(
    val baseUrl: HttpUrl,
    private val tokenProvider: () -> String?,
    private val onUnauthorized: () -> Unit,
    userAgent: String = "730Tracker-Android",
) {
    val okHttp: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS) // OCR of several photos can take a while
        .writeTimeout(180, TimeUnit.SECONDS)
        .addInterceptor(Interceptor { chain ->
            val req = chain.request().newBuilder().header("User-Agent", userAgent)
            val token = tokenProvider()
            if (token != null && chain.request().url.host == baseUrl.host) {
                req.header("Authorization", "Bearer $token")
            }
            val resp = chain.proceed(req.build())
            if (resp.code == 401 && token != null && !chain.request().url.encodedPath.endsWith("/auth/login")) {
                onUnauthorized()
            }
            resp
        })
        .build()

    val api: TrackerApi = Retrofit.Builder()
        .baseUrl(baseUrl)
        .client(okHttp)
        .addConverterFactory(TrackerJson.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(TrackerApi::class.java)

    fun fileUrl(receiptId: String, kind: String): String =
        baseUrl.newBuilder().addPathSegments("api/v1/receipts/$receiptId/files/$kind").build().toString()
}

/** Human-readable (Italian) message for any failure coming from the API layer. */
fun errorMessage(t: Throwable): String = when (t) {
    is HttpException -> {
        val body = try { t.response()?.errorBody()?.string() } catch (_: IOException) { null }
        parseErrorDetail(body) ?: when (t.code()) {
            401 -> "Sessione scaduta: accedi di nuovo."
            403 -> "Operazione non consentita."
            404 -> "Non trovato."
            413 -> "File troppo grande."
            in 500..599 -> "Errore del server (${t.code()})."
            else -> "Errore ${t.code()}."
        }
    }
    is java.net.UnknownHostException -> "Server non raggiungibile: controlla l'indirizzo e la connessione."
    is java.net.ConnectException -> "Impossibile connettersi al server."
    is java.net.SocketTimeoutException -> "Il server non ha risposto in tempo."
    is javax.net.ssl.SSLException -> "Connessione sicura non riuscita (certificato non valido?)."
    is IOException -> "Errore di rete: ${t.message ?: "connessione interrotta"}."
    else -> t.message ?: "Errore imprevisto."
}

/** Server errors look like {"detail": "…"}, {"detail": {"code","message"}} or {"detail": [{"msg": …}]}. */
fun parseErrorDetail(body: String?): String? {
    if (body.isNullOrBlank()) return null
    return try {
        val detail = TrackerJson.parseToJsonElement(body).jsonObject["detail"] ?: return null
        when (detail) {
            is JsonPrimitive -> detail.contentOrNull
            is JsonObject -> detail["message"]?.jsonPrimitive?.contentOrNull
            is JsonArray -> detail.mapNotNull { (it as? JsonObject)?.get("msg")?.jsonPrimitive?.contentOrNull }
                .joinToString("; ").ifBlank { null }
        }
    } catch (_: Exception) {
        null
    }
}

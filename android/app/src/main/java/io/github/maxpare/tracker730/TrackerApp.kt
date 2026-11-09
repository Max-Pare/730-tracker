// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730

import android.app.Application
import android.os.Build
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import io.github.maxpare.tracker730.data.ApiClient
import io.github.maxpare.tracker730.data.SessionStore
import io.github.maxpare.tracker730.data.TrackerApi
import io.github.maxpare.tracker730.data.errorMessage
import io.github.maxpare.tracker730.data.normalizeServerUrl
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlin.coroutines.cancellation.CancellationException

/** Process-wide dependencies. */
class AppContainer(app: Application) {
    val store = SessionStore(app)

    @Volatile var token: String? = null
    @Volatile var client: ApiClient? = null
        private set

    private val _unauthorized = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val unauthorized = _unauthorized.asSharedFlow()

    val deviceName: String = "${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}".take(80)

    fun connect(serverUrl: String): ApiClient {
        val base = requireNotNull(normalizeServerUrl(serverUrl)) { "Indirizzo non valido" }
        client?.let { if (it.baseUrl == base) return it }
        return ApiClient(base, { token }, { _unauthorized.tryEmit(Unit) }).also { client = it }
    }

    val api: TrackerApi get() = checkNotNull(client) { "Server non configurato" }.api

    /** Runs an API call, converting every failure into an Italian message. */
    suspend fun <T> call(block: suspend TrackerApi.() -> T): Result<T> = try {
        Result.success(api.block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Result.failure(ApiError(errorMessage(e), e))
    }
}

class ApiError(message: String, cause: Throwable?) : Exception(message, cause)

class TrackerApp : Application(), SingletonImageLoader.Factory {
    lateinit var container: AppContainer
        private set
    private val fallbackHttp by lazy { okhttp3.OkHttpClient() }

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }

    /** Receipt images are fetched with the user's token and never cached on disk. */
    override fun newImageLoader(context: PlatformContext): ImageLoader =
        ImageLoader.Builder(context)
            .components {
                // Coil evaluates callFactory once; delegate per call so a server switch is honoured.
                add(OkHttpNetworkFetcherFactory(callFactory = {
                    okhttp3.Call.Factory { request -> (container.client?.okHttp ?: fallbackHttp).newCall(request) }
                }))
            }
            .diskCache(null)
            .build()
}

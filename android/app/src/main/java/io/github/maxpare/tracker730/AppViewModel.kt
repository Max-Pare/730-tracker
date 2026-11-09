// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import io.github.maxpare.tracker730.data.LoginIn
import io.github.maxpare.tracker730.data.Meta
import io.github.maxpare.tracker730.data.Profile
import io.github.maxpare.tracker730.data.RecoverIn
import io.github.maxpare.tracker730.data.RegisterIn
import io.github.maxpare.tracker730.data.ServerInfo
import io.github.maxpare.tracker730.data.TokenOut
import io.github.maxpare.tracker730.data.UserOut
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

sealed interface Phase {
    data object Loading : Phase
    data object NeedsServer : Phase
    data object NeedsLogin : Phase
    data object Ready : Phase
}

data class AppState(
    val phase: Phase = Phase.Loading,
    val serverUrl: String = "",
    val serverInfo: ServerInfo? = null,
    val user: UserOut? = null,
    val lastUsername: String = "",
    val meta: Meta? = null,
    val profile: Profile = Profile(),
    val recoveryCode: String? = null,
    val busy: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
    /** Files shared into the app from elsewhere, waiting for upload. */
    val sharedUris: List<Uri> = emptyList(),
)

/** Session-level state: which server, who is logged in, shared lookups (categories, profile). */
class AppViewModel(private val c: AppContainer) : ViewModel() {
    private val _state = MutableStateFlow(AppState())
    val state: StateFlow<AppState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            val stored = c.store.load()
            if (stored.serverUrl == null) {
                _state.update { it.copy(phase = Phase.NeedsServer) }
                return@launch
            }
            c.connect(stored.serverUrl)
            c.token = stored.token
            _state.update { it.copy(serverUrl = stored.serverUrl, lastUsername = stored.username.orEmpty()) }
            if (stored.token == null) {
                loadServerInfo()
                _state.update { it.copy(phase = Phase.NeedsLogin) }
            } else {
                c.call { me() }.onSuccess { me ->
                    _state.update { it.copy(user = me.user, profile = me.profile, phase = Phase.Ready) }
                    loadMeta()
                }.onFailure { e ->
                    if (c.token == null) {
                        loadServerInfo()
                        _state.update { it.copy(phase = Phase.NeedsLogin) }
                    } else {
                        // Offline or server down: stay logged in, screens will show the error.
                        _state.update { it.copy(phase = Phase.Ready, error = e.message) }
                        loadMeta()
                    }
                }
            }
        }
        viewModelScope.launch {
            c.unauthorized.collect {
                c.token = null
                c.store.clearToken()
                loadServerInfo()
                _state.update { it.copy(phase = Phase.NeedsLogin, user = null, notice = "Sessione scaduta: accedi di nuovo.") }
            }
        }
    }

    private suspend fun loadServerInfo() {
        c.call { serverInfo() }.onSuccess { info -> _state.update { it.copy(serverInfo = info) } }
    }

    private fun loadMeta() = viewModelScope.launch {
        c.call { meta() }.onSuccess { m -> _state.update { it.copy(meta = m) } }
    }

    fun clearMessages() = _state.update { it.copy(error = null, notice = null) }

    fun showNotice(message: String) = _state.update { it.copy(notice = message) }

    fun setServer(url: String) = viewModelScope.launch {
        _state.update { it.copy(busy = true, error = null) }
        val client = try {
            c.connect(url)
        } catch (e: IllegalArgumentException) {
            _state.update { it.copy(busy = false, error = "Indirizzo non valido.") }
            return@launch
        }
        c.call { serverInfo() }
            .onSuccess { info ->
                val base = client.baseUrl.toString()
                c.store.saveServer(base)
                c.token = null
                _state.update { it.copy(busy = false, serverUrl = base, serverInfo = info, phase = Phase.NeedsLogin) }
            }
            .onFailure { e -> _state.update { it.copy(busy = false, error = e.message) } }
    }

    fun changeServer() {
        c.token = null
        _state.update { it.copy(phase = Phase.NeedsServer, user = null, error = null) }
    }

    private suspend fun onLoggedIn(out: TokenOut) {
        c.token = out.token
        c.store.saveLogin(out.token, out.user.username)
        _state.update { it.copy(busy = false, user = out.user, lastUsername = out.user.username, recoveryCode = out.recoveryCode) }
        refreshProfile()
        loadMeta()
        _state.update { it.copy(phase = Phase.Ready) }
    }

    fun login(username: String, password: String) = authCall { login(LoginIn(username.trim(), password, c.deviceName)) }

    fun register(username: String, password: String, invite: String?) =
        authCall { register(RegisterIn(username.trim(), password, invite?.trim()?.ifBlank { null }, c.deviceName)) }

    fun recover(username: String, code: String, newPassword: String) =
        authCall { recover(RecoverIn(username.trim(), code.trim(), newPassword, c.deviceName)) }

    private fun authCall(block: suspend io.github.maxpare.tracker730.data.TrackerApi.() -> TokenOut) = viewModelScope.launch {
        _state.update { it.copy(busy = true, error = null) }
        c.call(block)
            .onSuccess { onLoggedIn(it) }
            .onFailure { e -> _state.update { it.copy(busy = false, error = e.message) } }
    }

    fun recoveryCodeShown() = _state.update { it.copy(recoveryCode = null) }

    fun showRecoveryCode(code: String) = _state.update { it.copy(recoveryCode = code) }

    fun logout() = viewModelScope.launch {
        c.call { logout() }
        c.token = null
        c.store.clearToken()
        _state.update { AppState(phase = Phase.NeedsLogin, serverUrl = it.serverUrl, serverInfo = it.serverInfo, lastUsername = it.lastUsername) }
    }

    /** After the account was deleted on the server. */
    fun forgetSession() = viewModelScope.launch {
        c.token = null
        c.store.clearToken()
        _state.update { AppState(phase = Phase.NeedsLogin, serverUrl = it.serverUrl, serverInfo = it.serverInfo) }
    }

    suspend fun refreshProfile() {
        c.call { me() }.onSuccess { me -> _state.update { it.copy(profile = me.profile, user = me.user) } }
    }

    fun setProfile(p: Profile) = _state.update { it.copy(profile = p) }

    fun addShared(uris: List<Uri>) = _state.update { it.copy(sharedUris = it.sharedUris + uris) }

    fun consumeShared(): List<Uri> {
        val uris = _state.value.sharedUris
        _state.update { it.copy(sharedUris = emptyList()) }
        return uris
    }
}

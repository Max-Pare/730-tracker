// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import io.github.maxpare.tracker730.AppContainer
import io.github.maxpare.tracker730.AppState
import io.github.maxpare.tracker730.AppViewModel
import io.github.maxpare.tracker730.BuildConfig
import io.github.maxpare.tracker730.R
import io.github.maxpare.tracker730.data.FamilyIn
import io.github.maxpare.tracker730.data.Format
import io.github.maxpare.tracker730.data.PasswordIn
import io.github.maxpare.tracker730.data.PasswordOnlyIn
import io.github.maxpare.tracker730.data.Profile
import io.github.maxpare.tracker730.data.ProfileIn
import io.github.maxpare.tracker730.data.SessionInfo
import io.github.maxpare.tracker730.data.TaxCode
import io.github.maxpare.tracker730.ui.components.Banner
import io.github.maxpare.tracker730.ui.components.Chip
import io.github.maxpare.tracker730.ui.components.Dropdown
import io.github.maxpare.tracker730.ui.components.FormField
import io.github.maxpare.tracker730.ui.components.SectionCard
import io.github.maxpare.tracker730.ui.components.Tone
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AccountState(
    val sessions: List<SessionInfo> = emptyList(),
    val busy: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
    val accountDeleted: Boolean = false,
)

class AccountViewModel(private val c: AppContainer, private val app: AppViewModel) : ViewModel() {
    private val _state = MutableStateFlow(AccountState())
    val state = _state.asStateFlow()

    fun loadSessions() = viewModelScope.launch {
        c.call { sessions() }.onSuccess { s -> _state.update { it.copy(sessions = s) } }
    }

    private fun run(notice: String? = null, block: suspend () -> Result<*>) = viewModelScope.launch {
        _state.update { it.copy(busy = true, error = null, notice = null) }
        block()
            .onSuccess { _state.update { it.copy(busy = false, notice = notice) } }
            .onFailure { e -> _state.update { it.copy(busy = false, error = e.message) } }
    }

    private fun Result<Profile>.applyProfile(): Result<Profile> = onSuccess { app.setProfile(it) }

    fun saveProfile(name: String, cf: String, ok: String) = run(ok) {
        c.call { updateProfile(ProfileIn(name.ifBlank { null }, cf.trim().uppercase().ifBlank { null })) }.applyProfile()
    }

    fun addFamily(m: FamilyIn) = run { c.call { addFamily(m) }.applyProfile() }
    fun toggleDependent(id: String, m: FamilyIn) = run { c.call { updateFamily(id, m.copy(dependent = !m.dependent)) }.applyProfile() }
    fun removeFamily(id: String) = run { c.call { deleteFamily(id) }.applyProfile() }

    fun changePassword(current: String, new: String, ok: String) = run(ok) {
        c.call { changePassword(PasswordIn(current, new)) }.also { loadSessions() }
    }

    fun newRecoveryCode(current: String) = run {
        c.call { newRecoveryCode(PasswordOnlyIn(current)) }.onSuccess { app.showRecoveryCode(it.recoveryCode) }
    }

    fun revoke(id: String) = run { c.call { revokeSession(id) }.also { loadSessions() } }

    fun deleteAccount(current: String) = run {
        c.call { deleteAccount(PasswordOnlyIn(current)) }.onSuccess { _state.update { it.copy(accountDeleted = true) } }
    }
}

@Composable
fun AccountScreen(appState: AppState, app: AppViewModel, vm: AccountViewModel) {
    val st by vm.state.collectAsStateWithLifecycle()
    val profile = appState.profile
    LaunchedEffect(Unit) { vm.loadSessions() }
    LaunchedEffect(st.accountDeleted) { if (st.accountDeleted) app.forgetSession() }

    var name by rememberSaveable(profile.fullName) { mutableStateOf(profile.fullName.orEmpty()) }
    var cf by rememberSaveable(profile.taxCode) { mutableStateOf(profile.taxCode.orEmpty()) }
    var mName by rememberSaveable { mutableStateOf("") }
    var mCf by rememberSaveable { mutableStateOf("") }
    var mRel by rememberSaveable { mutableStateOf("figlio") }
    var mDep by rememberSaveable { mutableStateOf(true) }
    var curPw by rememberSaveable { mutableStateOf("") }
    var newPw by rememberSaveable { mutableStateOf("") }
    var newPw2 by rememberSaveable { mutableStateOf("") }
    var deleteDialog by rememberSaveable { mutableStateOf(false) }
    var deletePw by rememberSaveable { mutableStateOf("") }
    val savedText = stringResource(R.string.saved)
    val pwChanged = stringResource(R.string.password_changed)
    val mismatch = stringResource(R.string.passwords_mismatch)
    val cfInvalid = stringResource(R.string.tax_code_invalid)
    var localError by rememberSaveable { mutableStateOf<String?>(null) }

    Column(
        Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(stringResource(R.string.account_title), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        appState.user?.let { Text("${it.username}${if (it.isAdmin) " · amministratore" else ""}", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        localError?.let { Banner(it, Tone.Bad) }
        st.error?.let { Banner(it, Tone.Bad) }
        st.notice?.let { Banner(it, Tone.Ok) }

        SectionCard(title = stringResource(R.string.profile_title)) {
            Text(stringResource(R.string.profile_body), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            FormField(name, { name = it }, stringResource(R.string.full_name))
            FormField(cf, { cf = it }, stringResource(R.string.tax_code), capitalizeCharacters = true, isError = cf.isNotBlank() && !TaxCode.isValid(cf))
            Button(onClick = {
                localError = if (cf.isNotBlank() && !TaxCode.isValid(cf)) cfInvalid else null
                if (localError == null) vm.saveProfile(name, cf, savedText)
            }, enabled = !st.busy) { Text(stringResource(R.string.save)) }
        }

        SectionCard(title = stringResource(R.string.family_title)) {
            Text(stringResource(R.string.family_body), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            profile.family.forEach { m ->
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text(m.name, fontWeight = FontWeight.SemiBold)
                        Text(listOfNotNull(appState.meta?.relations?.firstOrNull { it.code == m.relation }?.label, m.taxCode).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    TextButton(onClick = { vm.toggleDependent(m.id, FamilyIn(m.name, m.taxCode, m.relation, m.dependent)) }) {
                        Chip(stringResource(if (m.dependent) R.string.dependent_yes else R.string.dependent_no), if (m.dependent) Tone.Ok else Tone.Bad)
                    }
                    TextButton(onClick = { vm.removeFamily(m.id) }) { Text(stringResource(R.string.delete)) }
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }
            Text(stringResource(R.string.family_add), fontWeight = FontWeight.SemiBold)
            FormField(mName, { mName = it }, stringResource(R.string.family_name))
            FormField(mCf, { mCf = it }, stringResource(R.string.tax_code), capitalizeCharacters = true, isError = mCf.isNotBlank() && !TaxCode.isValid(mCf))
            Dropdown(stringResource(R.string.family_relation), appState.meta?.relations?.map { it.code to it.label } ?: listOf("altro" to "Altro"),
                mRel, { mRel = it }, Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = mDep, onCheckedChange = { mDep = it }); Text(stringResource(R.string.family_dependent))
            }
            OutlinedButton(onClick = {
                localError = if (mCf.isNotBlank() && !TaxCode.isValid(mCf)) cfInvalid else null
                if (localError == null && mName.isNotBlank()) {
                    vm.addFamily(FamilyIn(mName.trim(), mCf.trim().uppercase().ifBlank { null }, mRel, mDep)); mName = ""; mCf = ""
                }
            }, enabled = !st.busy && mName.isNotBlank()) { Text(stringResource(R.string.family_add)) }
        }

        SectionCard(title = stringResource(R.string.password_title)) {
            FormField(curPw, { curPw = it }, stringResource(R.string.current_password), password = true)
            FormField(newPw, { newPw = it }, stringResource(R.string.new_password), password = true, hint = stringResource(R.string.register_password_hint))
            FormField(newPw2, { newPw2 = it }, stringResource(R.string.password_repeat), password = true)
            Button(onClick = {
                localError = if (newPw != newPw2) mismatch else null
                if (localError == null) { vm.changePassword(curPw, newPw, pwChanged); newPw = ""; newPw2 = "" }
            }, enabled = !st.busy && curPw.isNotBlank() && newPw.isNotBlank()) { Text(stringResource(R.string.change_password)) }
            OutlinedButton(onClick = { vm.newRecoveryCode(curPw) }, enabled = !st.busy && curPw.isNotBlank()) {
                Text(stringResource(R.string.new_recovery_code))
            }
        }

        SectionCard(title = stringResource(R.string.devices_title)) {
            st.sessions.forEach { s ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(s.label ?: if (s.kind == "api") "App" else "Browser", fontWeight = FontWeight.SemiBold)
                            if (s.current) Chip(stringResource(R.string.this_device), Tone.Ok)
                        }
                        Text(Format.dateTime(s.lastSeenAt), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (!s.current) TextButton(onClick = { vm.revoke(s.id) }) { Text(stringResource(R.string.disconnect)) }
                }
            }
            Button(onClick = { app.logout() }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.logout)) }
        }

        SectionCard(title = stringResource(R.string.delete_account)) {
            Text(stringResource(R.string.delete_account_body))
            TextButton(onClick = { deleteDialog = true }) { Text(stringResource(R.string.delete_account), color = MaterialTheme.colorScheme.error) }
        }
        Text(stringResource(R.string.server_label, appState.serverUrl), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(stringResource(R.string.about, BuildConfig.VERSION_NAME), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }

    if (deleteDialog) {
        AlertDialog(
            onDismissRequest = { deleteDialog = false },
            title = { Text(stringResource(R.string.delete_account)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(stringResource(R.string.delete_account_body))
                    FormField(deletePw, { deletePw = it }, stringResource(R.string.current_password), password = true)
                }
            },
            confirmButton = {
                TextButton(onClick = { deleteDialog = false; vm.deleteAccount(deletePw); deletePw = "" }, enabled = deletePw.isNotBlank()) {
                    Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { deleteDialog = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

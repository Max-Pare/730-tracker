// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Row
import io.github.maxpare.tracker730.AppState
import io.github.maxpare.tracker730.AppViewModel
import io.github.maxpare.tracker730.R
import io.github.maxpare.tracker730.ui.components.Banner
import io.github.maxpare.tracker730.ui.components.FormField
import io.github.maxpare.tracker730.ui.components.SectionCard
import io.github.maxpare.tracker730.ui.components.SmallSpinner
import io.github.maxpare.tracker730.ui.components.Tone

@Composable
private fun AuthScaffold(content: @Composable () -> Unit) {
    Column(
        Modifier.fillMaxSize().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState()).padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(Modifier.widthIn(max = 480.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Image(painterResource(R.drawable.ic_logo), contentDescription = null, modifier = Modifier.size(36.dp))
                Text(stringResource(R.string.app_name), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            }
            content()
        }
    }
}

@Composable
private fun ErrorAndNotice(state: AppState) {
    state.notice?.let { Banner(it, Tone.Info) }
    state.error?.let { Banner(it, Tone.Bad) }
}

@Composable
fun ServerSetupScreen(state: AppState, vm: AppViewModel) {
    var url by rememberSaveable { mutableStateOf(state.serverUrl) }
    AuthScaffold {
        SectionCard(title = stringResource(R.string.setup_title)) {
            Text(stringResource(R.string.setup_body))
            FormField(url, { url = it }, stringResource(R.string.setup_url), hint = stringResource(R.string.setup_url_hint), keyboardType = KeyboardType.Uri)
            if (url.trim().startsWith("http://", ignoreCase = true)) Banner(stringResource(R.string.setup_http_warning), Tone.Warn)
            ErrorAndNotice(state)
            Button(onClick = { vm.setServer(url) }, enabled = !state.busy && url.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
                if (state.busy) SmallSpinner() else Text(stringResource(R.string.setup_connect))
            }
        }
    }
}

enum class AuthMode { Login, Register, Recover }

@Composable
fun AuthScreen(state: AppState, vm: AppViewModel) {
    val needsSetup = state.serverInfo?.needsSetup == true
    var mode by rememberSaveable { mutableStateOf(if (needsSetup) AuthMode.Register else AuthMode.Login) }
    var username by rememberSaveable { mutableStateOf(state.lastUsername) }
    var password by rememberSaveable { mutableStateOf("") }
    var password2 by rememberSaveable { mutableStateOf("") }
    var invite by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var localError by rememberSaveable { mutableStateOf<String?>(null) }
    val mismatch = stringResource(R.string.passwords_mismatch)
    val canRegister = needsSetup || state.serverInfo?.registrationMode != "closed"

    AuthScaffold {
        SectionCard(
            title = when (mode) {
                AuthMode.Login -> stringResource(R.string.login_title)
                AuthMode.Register -> stringResource(if (needsSetup) R.string.register_first_title else R.string.register_title)
                AuthMode.Recover -> stringResource(R.string.recover_title)
            }
        ) {
            if (mode == AuthMode.Register && needsSetup) Banner(stringResource(R.string.register_first_body), Tone.Info)
            if (mode == AuthMode.Recover) Text(stringResource(R.string.recover_body))
            FormField(username, { username = it }, stringResource(R.string.username), keyboardType = KeyboardType.Email)
            if (mode == AuthMode.Recover) {
                FormField(code, { code = it }, stringResource(R.string.recover_code), capitalizeCharacters = true)
            }
            FormField(
                password, { password = it },
                stringResource(if (mode == AuthMode.Recover) R.string.new_password else R.string.password),
                password = true,
                hint = if (mode != AuthMode.Login) stringResource(R.string.register_password_hint) else null,
            )
            if (mode != AuthMode.Login) FormField(password2, { password2 = it }, stringResource(R.string.password_repeat), password = true)
            if (mode == AuthMode.Register && !needsSetup && state.serverInfo?.registrationMode != "open") {
                FormField(invite, { invite = it }, stringResource(R.string.register_invite), hint = stringResource(R.string.register_invite_hint))
            }
            if (mode == AuthMode.Register) Banner(stringResource(R.string.register_warning), Tone.Warn)
            localError?.let { Banner(it, Tone.Bad) }
            ErrorAndNotice(state)
            Button(
                onClick = {
                    localError = null
                    vm.clearMessages()
                    if (mode != AuthMode.Login && password != password2) { localError = mismatch; return@Button }
                    when (mode) {
                        AuthMode.Login -> vm.login(username, password)
                        AuthMode.Register -> vm.register(username, password, invite)
                        AuthMode.Recover -> vm.recover(username, code, password)
                    }
                },
                enabled = !state.busy && username.isNotBlank() && password.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.busy) SmallSpinner() else Text(
                    stringResource(
                        when (mode) {
                            AuthMode.Login -> R.string.login_button
                            AuthMode.Register -> R.string.register_button
                            AuthMode.Recover -> R.string.recover_button
                        }
                    )
                )
            }
        }
        if (!needsSetup) {
            Column {
                if (mode != AuthMode.Login) TextButton(onClick = { mode = AuthMode.Login; vm.clearMessages() }) { Text(stringResource(R.string.login_title)) }
                if (mode != AuthMode.Recover) TextButton(onClick = { mode = AuthMode.Recover; vm.clearMessages() }) { Text(stringResource(R.string.login_forgot)) }
                if (mode != AuthMode.Register && canRegister) TextButton(onClick = { mode = AuthMode.Register; vm.clearMessages() }) { Text(stringResource(R.string.login_register)) }
            }
        }
        Text(stringResource(R.string.login_privacy), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(stringResource(R.string.server_label, state.serverUrl), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        TextButton(onClick = { vm.changeServer() }) { Text(stringResource(R.string.change_server)) }
    }
}

@Composable
fun RecoveryCodeScreen(code: String, onDone: () -> Unit) {
    val clipboard = LocalClipboardManager.current
    var saved by rememberSaveable { mutableStateOf(false) }
    var copied by rememberSaveable { mutableStateOf(false) }
    AuthScaffold {
        SectionCard(title = stringResource(R.string.recovery_code_title)) {
            Text(stringResource(R.string.recovery_code_body))
            SelectionContainer {
                Text(
                    code,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 20.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                )
            }
            OutlinedButton(onClick = { clipboard.setText(AnnotatedString(code)); copied = true }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(if (copied) R.string.recovery_code_copied else R.string.recovery_code_copy))
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = saved, onCheckedChange = { saved = it })
                Text(stringResource(R.string.recovery_code_saved))
            }
            Spacer(Modifier.height(4.dp))
            Button(onClick = onDone, enabled = saved, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.confirm)) }
        }
    }
}

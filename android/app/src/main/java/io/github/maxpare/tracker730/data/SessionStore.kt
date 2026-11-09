// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Encrypts small secrets before they are written to disk. */
interface SecretCipher {
    fun encrypt(plain: String): String
    fun decrypt(encoded: String): String?
}

/**
 * AES-256-GCM with a non-exportable key held by the Android Keystore
 * (hardware-backed where available). The API token never touches disk in clear.
 */
class KeystoreCipher(private val alias: String = "tracker730_session") : SecretCipher {
    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(alias, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return gen.generateKey()
    }

    override fun encrypt(plain: String): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        val ct = c.doFinal(plain.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(c.iv + ct, Base64.NO_WRAP)
    }

    override fun decrypt(encoded: String): String? = try {
        val raw = Base64.decode(encoded, Base64.NO_WRAP)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw, 0, 12))
        String(c.doFinal(raw, 12, raw.size - 12), Charsets.UTF_8)
    } catch (_: Exception) {
        null // key lost (e.g. device restored): the user simply logs in again
    }
}

private val Context.dataStore by preferencesDataStore(name = "session")

data class StoredSession(val serverUrl: String?, val token: String?, val username: String?)

class SessionStore(private val context: Context, private val cipher: SecretCipher = KeystoreCipher()) {
    private val kServer = stringPreferencesKey("server_url")
    private val kToken = stringPreferencesKey("token_enc")
    private val kUser = stringPreferencesKey("username")

    suspend fun load(): StoredSession {
        val p = context.dataStore.data.first()
        return StoredSession(
            serverUrl = p[kServer],
            token = p[kToken]?.let { cipher.decrypt(it) },
            username = p[kUser],
        )
    }

    suspend fun saveServer(url: String) {
        context.dataStore.edit {
            if (it[kServer] != url) it.remove(kToken)
            it[kServer] = url
        }
    }

    suspend fun saveLogin(token: String, username: String) {
        // If the keystore is unusable the token is kept in memory only (login again next launch);
        // it is never written to disk unencrypted.
        val encrypted = try { cipher.encrypt(token) } catch (_: Exception) { null }
        context.dataStore.edit {
            if (encrypted != null) it[kToken] = encrypted else it.remove(kToken)
            it[kUser] = username
        }
    }

    suspend fun clearToken() {
        context.dataStore.edit { it.remove(kToken) }
    }
}

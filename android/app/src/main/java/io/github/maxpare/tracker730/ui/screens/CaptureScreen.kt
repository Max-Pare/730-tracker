// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui.screens

import android.content.ActivityNotFoundException
import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import coil3.compose.AsyncImage
import io.github.maxpare.tracker730.AppContainer
import io.github.maxpare.tracker730.R
import io.github.maxpare.tracker730.data.Format
import io.github.maxpare.tracker730.data.UploadResult
import io.github.maxpare.tracker730.ui.components.Banner
import io.github.maxpare.tracker730.ui.components.Tone
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okio.BufferedSink
import okio.source
import java.io.IOException
import java.io.File

data class PendingFile(val uri: Uri, val name: String, val mime: String, val isCapture: Boolean)

data class CaptureState(
    val files: List<PendingFile> = emptyList(),
    val uploading: Boolean = false,
    val error: String? = null,
    val result: UploadResult? = null,
)

class CaptureViewModel(private val c: AppContainer) : ViewModel() {
    private val _state = MutableStateFlow(CaptureState())
    val state = _state.asStateFlow()

    fun add(files: List<PendingFile>) = _state.update { it.copy(files = it.files + files, error = null) }
    fun remove(f: PendingFile, context: Context) {
        _state.update { it.copy(files = it.files - f) }
        if (f.isCapture) deleteCapture(context, f.uri)
    }
    fun resultHandled() = _state.update { it.copy(result = null) }

    fun upload(context: Context) = viewModelScope.launch {
        val files = _state.value.files
        if (files.isEmpty()) return@launch
        _state.update { it.copy(uploading = true, error = null) }
        val resolver = context.applicationContext.contentResolver
        val parts = files.map { f ->
            MultipartBody.Part.createFormData("files", f.name, UriRequestBody(resolver, f.uri, f.mime))
        }
        c.call { upload(parts) }
            .onSuccess { res ->
                files.filter { it.isCapture }.forEach { deleteCapture(context, it.uri) }
                _state.update { it.copy(uploading = false, files = emptyList(), result = res) }
            }
            .onFailure { e -> _state.update { it.copy(uploading = false, error = e.message) } }
    }

    private fun deleteCapture(context: Context, uri: Uri) {
        try { context.contentResolver.delete(uri, null, null) } catch (_: Exception) { }
    }
}

/** Streams a content:// file into the request body, so large photos are never fully held in memory. */
class UriRequestBody(private val resolver: ContentResolver, private val uri: Uri, mime: String) : RequestBody() {
    private val type = mime.toMediaTypeOrNull()
    override fun contentType() = type
    override fun contentLength(): Long =
        resolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else -1L
        } ?: -1L
    override fun writeTo(sink: BufferedSink) {
        val input = resolver.openInputStream(uri) ?: throw IOException("Impossibile leggere il file")
        input.source().use { sink.writeAll(it) }
    }
}

fun describeUri(resolver: ContentResolver, uri: Uri, fallbackName: String): PendingFile {
    var name = fallbackName
    resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
        if (c.moveToFirst()) c.getString(0)?.let { name = it }
    }
    val mime = resolver.getType(uri) ?: if (name.endsWith(".pdf", true)) "application/pdf" else "image/jpeg"
    return PendingFile(uri, name, mime, isCapture = false)
}

private fun newCaptureUri(context: Context): Uri {
    val dir = File(context.cacheDir, "captures").apply { mkdirs() }
    val file = File.createTempFile("scontrino_", ".jpg", dir)
    return FileProvider.getUriForFile(context, "${context.packageName}.files", file)
}

@Composable
fun CaptureScreen(
    vm: CaptureViewModel,
    shared: List<Uri>,
    onSharedConsumed: () -> Unit,
    onDone: (UploadResult) -> Unit,
    onManual: () -> Unit,
) {
    val st by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var pendingCapture by rememberSaveable { mutableStateOf<Uri?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }
    val noCamera = stringResource(R.string.capture_no_camera)

    LaunchedEffect(shared) {
        if (shared.isNotEmpty()) {
            vm.add(shared.mapIndexed { i, u -> describeUri(context.contentResolver, u, "condiviso_${i + 1}") })
            onSharedConsumed()
        }
    }
    LaunchedEffect(st.result) { st.result?.let { onDone(it); vm.resultHandled() } }

    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val uri = pendingCapture
        if (ok && uri != null) {
            vm.add(listOf(PendingFile(uri, "foto_${System.currentTimeMillis()}.jpg", "image/jpeg", isCapture = true)))
        } else if (uri != null) {
            try { context.contentResolver.delete(uri, null, null) } catch (_: Exception) { }
        }
        pendingCapture = null
    }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(20)) { uris ->
        vm.add(uris.mapIndexed { i, u -> describeUri(context.contentResolver, u, "foto_${i + 1}.jpg") })
    }
    val pdfs = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        vm.add(uris.mapIndexed { i, u -> describeUri(context.contentResolver, u, "documento_${i + 1}.pdf") })
    }

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.capture_title), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(stringResource(R.string.capture_body), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(
                onClick = {
                    val uri = newCaptureUri(context)
                    pendingCapture = uri
                    try { camera.launch(uri) } catch (_: ActivityNotFoundException) { notice = noCamera }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                enabled = !st.uploading,
            ) {
                Icon(Icons.Default.PhotoCamera, contentDescription = null)
                Text("  " + stringResource(R.string.capture_camera))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                    modifier = Modifier.weight(1f), enabled = !st.uploading,
                ) { Icon(Icons.Default.PhotoLibrary, contentDescription = null); Text("  " + stringResource(R.string.capture_gallery)) }
                OutlinedButton(
                    onClick = { pdfs.launch(arrayOf("application/pdf")) },
                    modifier = Modifier.weight(1f), enabled = !st.uploading,
                ) { Icon(Icons.Default.PictureAsPdf, contentDescription = null); Text("  " + stringResource(R.string.capture_pdf)) }
            }
            Banner(stringResource(R.string.capture_tips), Tone.Info)
            notice?.let { Banner(it, Tone.Warn) }
            st.error?.let { Banner(it, Tone.Bad) }

            LazyVerticalGrid(columns = GridCells.Adaptive(96.dp), modifier = Modifier.weight(1f),
                horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(st.files, key = { it.uri.toString() }) { f ->
                    Box(Modifier.aspectRatio(3f / 4f).clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.surfaceVariant)) {
                        if (f.mime.startsWith("image/")) {
                            AsyncImage(model = f.uri, contentDescription = f.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                        } else {
                            Icon(Icons.Default.Description, contentDescription = f.name, modifier = Modifier.align(Alignment.Center).size(40.dp))
                        }
                        IconButton(
                            onClick = { vm.remove(f, context) },
                            modifier = Modifier.align(Alignment.TopEnd).padding(2.dp).size(28.dp)
                                .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.6f), CircleShape),
                        ) { Icon(Icons.Default.Close, contentDescription = stringResource(R.string.capture_remove), tint = MaterialTheme.colorScheme.surface) }
                    }
                }
            }
            Button(onClick = { vm.upload(context) }, enabled = st.files.isNotEmpty() && !st.uploading, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.capture_process, st.files.size))
            }
            TextButton(onClick = onManual, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Default.Edit, contentDescription = null); Text("  " + stringResource(R.string.capture_manual))
            }
        }
        if (st.uploading) {
            Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.5f)), contentAlignment = Alignment.Center) {
                Column(
                    Modifier.background(MaterialTheme.colorScheme.surface, RoundedCornerShape(16.dp)).padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    CircularProgressIndicator()
                    Text(stringResource(R.string.capture_processing), fontWeight = FontWeight.SemiBold)
                    Text(Format.documents(st.files.size), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import io.github.maxpare.tracker730.AppContainer
import io.github.maxpare.tracker730.R
import io.github.maxpare.tracker730.data.Format
import io.github.maxpare.tracker730.data.Meta
import io.github.maxpare.tracker730.data.ReceiptOut
import io.github.maxpare.tracker730.ui.components.Banner
import io.github.maxpare.tracker730.ui.components.Chip
import io.github.maxpare.tracker730.ui.components.Dropdown
import io.github.maxpare.tracker730.ui.components.Tone
import io.github.maxpare.tracker730.ui.components.toneForStatus
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ArchiveState(
    val loading: Boolean = false,
    val items: List<ReceiptOut> = emptyList(),
    val total: Int = 0,
    val totalAmount: Long = 0,
    val page: Int = 1,
    val pages: Int = 1,
    val query: String = "",
    val year: Int? = null,
    val status: String? = null,
    val years: List<Int> = emptyList(),
    val error: String? = null,
)

class ArchiveViewModel(private val c: AppContainer) : ViewModel() {
    private val _state = MutableStateFlow(ArchiveState())
    val state = _state.asStateFlow()
    private var searchJob: Job? = null

    fun setStatus(status: String?) { _state.update { it.copy(status = status) }; reload() }
    fun setYear(year: Int?) { _state.update { it.copy(year = year) }; reload() }
    fun setQuery(q: String) {
        _state.update { it.copy(query = q) }
        searchJob?.cancel()
        searchJob = viewModelScope.launch { delay(350); load(1) }
    }

    fun reload() = viewModelScope.launch { load(1) }
    fun more() = viewModelScope.launch { load(_state.value.page + 1) }

    private suspend fun load(page: Int) {
        val s = _state.value
        _state.update { it.copy(loading = true, error = null) }
        if (s.years.isEmpty()) c.call { dashboard(null) }.onSuccess { d -> _state.update { it.copy(years = d.years) } }
        val sort = if (s.status == "bozza") "created_desc" else "date_desc"
        c.call { receipts(year = s.year, status = s.status, q = s.query.ifBlank { null }, sort = sort, page = page) }
            .onSuccess { p ->
                _state.update {
                    it.copy(
                        loading = false,
                        items = if (page == 1) p.items else it.items + p.items,
                        total = p.total, totalAmount = p.totalAmountCents, page = p.page, pages = p.pages,
                    )
                }
            }
            .onFailure { e -> _state.update { it.copy(loading = false, error = e.message) } }
    }
}

@Composable
fun ArchiveScreen(vm: ArchiveViewModel, meta: Meta?, initialStatus: String?, onOpen: (String) -> Unit) {
    val st by vm.state.collectAsStateWithLifecycle()
    LaunchedEffect(initialStatus) {
        if (initialStatus != null && st.status != initialStatus) vm.setStatus(initialStatus) else vm.reload()
    }
    val all = stringResource(R.string.filter_all)
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = st.query,
                onValueChange = vm::setQuery,
                placeholder = { Text(stringResource(R.string.search_hint)) },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Dropdown(
                    label = stringResource(R.string.filter_year),
                    options = listOf<Pair<Int?, String>>(null to all) + st.years.map { it to it.toString() },
                    selected = st.year,
                    onSelect = vm::setYear,
                    modifier = Modifier.weight(1f),
                )
                Dropdown(
                    label = stringResource(R.string.filter_status),
                    options = listOf<Pair<String?, String>>(null to all) + (meta?.statuses?.map { it.code to it.label } ?: emptyList()),
                    selected = st.status,
                    onSelect = vm::setStatus,
                    modifier = Modifier.weight(1.4f),
                )
            }
            Text(
                stringResource(R.string.archive_summary, Format.documents(st.total), Format.euro(st.totalAmount)),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            st.error?.let { Banner(it, Tone.Bad) }
        }
        PullToRefreshBox(isRefreshing = st.loading, onRefresh = { vm.reload() }, modifier = Modifier.fillMaxSize()) {
            LazyColumn(contentPadding = PaddingValues(bottom = 24.dp), modifier = Modifier.fillMaxSize()) {
                if (st.items.isEmpty() && !st.loading) item {
                    Text(stringResource(R.string.archive_empty), modifier = Modifier.padding(16.dp))
                }
                items(st.items, key = { it.id }) { r ->
                    ReceiptRow(r, meta) { onOpen(r.id) }
                    HorizontalDivider(Modifier.padding(horizontal = 16.dp), color = MaterialTheme.colorScheme.outlineVariant)
                }
                if (st.page < st.pages) item {
                    TextButton(onClick = { vm.more() }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.load_more)) }
                }
            }
        }
    }
}

@Composable
private fun ReceiptRow(r: ReceiptOut, meta: Meta?, onClick: () -> Unit) {
    val d = r.data
    val catLabel = meta?.categories?.firstOrNull { it.code == d.category }?.label
    val statusLabel = meta?.statuses?.firstOrNull { it.code == d.status }?.label ?: d.status
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                d.providerName ?: d.originalFilename ?: stringResource(R.string.no_name),
                fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            Text(Format.euro(d.amountCents), fontWeight = FontWeight.Bold)
        }
        Text(
            listOf(
                Format.date(d.date).ifBlank { stringResource(R.string.no_date) },
                catLabel ?: stringResource(R.string.no_category),
                r.beneficiaryLabel,
            ).joinToString(" · "),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1, overflow = TextOverflow.Ellipsis,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            if (d.status != "verificato") Chip(statusLabel, toneForStatus(d.status))
            Chip(r.evaluation.label, toneForStatus(r.evaluation.status))
        }
    }
}

@Composable
fun RetryBox(message: String, onRetry: () -> Unit) {
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Banner(message, Tone.Bad)
        Button(onClick = onRetry) { Text(stringResource(R.string.retry)) }
    }
}

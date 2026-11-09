// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui.screens

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import io.github.maxpare.tracker730.AppContainer
import io.github.maxpare.tracker730.R
import io.github.maxpare.tracker730.data.Bucket
import io.github.maxpare.tracker730.data.Dashboard
import io.github.maxpare.tracker730.data.Format
import io.github.maxpare.tracker730.ui.components.Banner
import io.github.maxpare.tracker730.ui.components.Chip
import io.github.maxpare.tracker730.ui.components.Dropdown
import io.github.maxpare.tracker730.ui.components.LoadingBox
import io.github.maxpare.tracker730.ui.components.SectionCard
import io.github.maxpare.tracker730.ui.components.Tone
import io.github.maxpare.tracker730.ui.theme.LocalStatusColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

data class DashboardState(
    val loading: Boolean = true,
    val year: Int? = null,
    val data: Dashboard? = null,
    val error: String? = null,
)

class DashboardViewModel(private val c: AppContainer) : ViewModel() {
    private val _state = MutableStateFlow(DashboardState())
    val state = _state.asStateFlow()

    fun load(year: Int? = _state.value.year) = viewModelScope.launch {
        _state.update { it.copy(loading = true, error = null) }
        c.call { dashboard(year) }
            .onSuccess { d -> _state.update { it.copy(loading = false, data = d, year = d.summary.year) } }
            .onFailure { e -> _state.update { it.copy(loading = false, error = e.message) } }
    }

    /** Downloads an export into the app cache and returns a shareable file. */
    suspend fun export(context: Context, zip: Boolean): Result<File> {
        val year = _state.value.year
        return c.call { if (zip) exportZip(year) else exportCsv(year) }.mapCatching { body ->
            withContext(Dispatchers.IO) {
                val dir = File(context.cacheDir, "exports").apply { mkdirs(); listFiles()?.forEach { it.delete() } }
                val f = File(dir, if (zip) "archivio-730-${year ?: "tutte"}.zip" else "spese-sanitarie-${year ?: "tutte"}.csv")
                body.byteStream().use { input -> f.outputStream().use { input.copyTo(it) } }
                f
            }
        }
    }
}

fun shareFile(context: Context, file: File, mime: String) {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    val send = Intent(Intent.ACTION_SEND).apply {
        type = mime
        putExtra(Intent.EXTRA_STREAM, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(Intent.createChooser(send, file.name))
}

@Composable
fun DashboardScreen(
    vm: DashboardViewModel,
    onOpenReceipt: (String) -> Unit,
    onOpenDrafts: () -> Unit,
    onAdd: () -> Unit,
) {
    val st by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { vm.load() }

    val d = st.data
    if (d == null) {
        if (st.error != null) Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Banner(st.error!!, Tone.Bad)
            Button(onClick = { vm.load() }) { Text(stringResource(R.string.retry)) }
        } else LoadingBox()
        return
    }
    val s = d.summary
    val exportFailed = stringResource(R.string.export_failed)
    PullToRefreshBox(isRefreshing = st.loading, onRefresh = { vm.load() }) {
        LazyColumn(
            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(stringResource(R.string.dashboard_title, s.year), style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    Dropdown(
                        label = "",
                        options = d.years.map { it to it.toString() },
                        selected = s.year,
                        onSelect = { vm.load(it) },
                        modifier = Modifier.size(width = 130.dp, height = 64.dp),
                    )
                }
                Text(stringResource(R.string.dashboard_return, s.year, s.returnLabel), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            st.error?.let { item { Banner(it, Tone.Bad) } }
            if (d.draftsTotal > 0) item {
                Banner(
                    stringResource(R.string.dashboard_drafts, Format.documents(d.draftsTotal)), Tone.Info,
                    modifier = Modifier.clickable { onOpenDrafts() },
                )
            }
            if (s.receiptsCount == 0 && d.draftsTotal == 0) item {
                SectionCard(title = stringResource(R.string.empty_title)) {
                    Text(stringResource(R.string.empty_body))
                    Button(onClick = onAdd) { Text(stringResource(R.string.nav_add)) }
                }
            }
            item { HeroKpi(s.detractionTotalCents) }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Kpi(stringResource(R.string.kpi_eligible), s.sanitarieEligibleCents + s.vetEligibleCents, null, Modifier.weight(1f))
                    Kpi(stringResource(R.string.kpi_total), s.totalSpentCents, Format.documents(s.receiptsCount), Modifier.weight(1f))
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Kpi(stringResource(R.string.kpi_uncertain), s.uncertainCents, null, Modifier.weight(1f))
                    Kpi(stringResource(R.string.kpi_non_deductible), s.nonDeductibleCents, Format.documents(s.nonDeductibleCount), Modifier.weight(1f))
                }
            }
            item {
                SectionCard(title = stringResource(R.string.franchise_title)) {
                    if (s.franchiseRemainingCents > 0) {
                        Text(stringResource(R.string.franchise_missing, Format.euro(s.franchiseRemainingCents), Format.euro(s.franchiseCents)))
                    } else {
                        Text(stringResource(R.string.franchise_done, Format.euro(s.sanitarieBaseCents)))
                    }
                    ProgressBar(s.sanitarieEligibleCents.toFloat() / s.franchiseCents.coerceAtLeast(1))
                    if (s.instalmentsPossible) Banner(stringResource(R.string.instalments), Tone.Info)
                    if (s.vetEligibleCents > 0) Text(
                        stringResource(R.string.vet_line, Format.euro(s.vetEligibleCents), Format.euro(s.vetDetractionCents)),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            item { SectionCard(title = stringResource(R.string.by_month)) { MonthChart(s.byMonth) } }
            item { SectionCard(title = stringResource(R.string.by_category)) { HBars(s.byCategory) } }
            item { SectionCard(title = stringResource(R.string.by_person)) { HBars(s.byBeneficiary) } }
            item {
                SectionCard(title = stringResource(R.string.issues_title)) {
                    if (s.issues.isEmpty()) Text(stringResource(R.string.issues_none), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            items(s.issues.sortedBy { if (it.severity == "warning") 0 else 1 }.take(30)) { issue ->
                Column(
                    Modifier.fillMaxWidth().clickable { onOpenReceipt(issue.receiptId) }.padding(horizontal = 16.dp, vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(issue.title, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary,
                            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                        Chip(if (issue.severity == "warning") "Attenzione" else "Nota", if (issue.severity == "warning") Tone.Warn else Tone.Info)
                    }
                    Text(issue.message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            item {
                SectionCard(title = stringResource(R.string.export_title)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = {
                            scope.launch {
                                vm.export(context, zip = false).onSuccess { shareFile(context, it, "text/csv") }
                                    .onFailure { android.widget.Toast.makeText(context, it.message ?: exportFailed, android.widget.Toast.LENGTH_LONG).show() }
                            }
                        }) { Text(stringResource(R.string.export_csv)) }
                        OutlinedButton(onClick = {
                            scope.launch {
                                vm.export(context, zip = true).onSuccess { shareFile(context, it, "application/zip") }
                                    .onFailure { android.widget.Toast.makeText(context, it.message ?: exportFailed, android.widget.Toast.LENGTH_LONG).show() }
                            }
                        }) { Text(stringResource(R.string.export_zip)) }
                    }
                }
            }
            item {
                Text(stringResource(R.string.disclaimer), style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(8.dp))
            }
        }
    }
}

@Composable
private fun HeroKpi(cents: Long) {
    Card(
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primary, contentColor = MaterialTheme.colorScheme.onPrimary),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(18.dp)) {
            Text(stringResource(R.string.kpi_detraction), style = MaterialTheme.typography.labelLarge)
            Text(Format.euro(cents), style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.Bold)
            Text(stringResource(R.string.kpi_detraction_sub), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun Kpi(label: String, cents: Long, sub: String?, modifier: Modifier = Modifier) {
    SectionCard(modifier = modifier) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(Format.euro(cents), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, maxLines = 1)
        if (sub != null) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun ProgressBar(fraction: Float) {
    val c = LocalStatusColors.current
    Canvas(Modifier.fillMaxWidth().height(10.dp)) {
        val r = CornerRadius(size.height / 2)
        drawRoundRect(c.chartTotal, cornerRadius = r)
        val f = fraction.coerceIn(0f, 1f)
        if (f > 0f) drawRoundRect(c.chartMain, size = Size(size.width * f.coerceAtLeast(0.02f), size.height), cornerRadius = r)
    }
}

@Composable
private fun MonthChart(months: List<Bucket>) {
    val c = LocalStatusColors.current
    val max = (months.maxOfOrNull { it.totalCents } ?: 0L).coerceAtLeast(1L).toFloat()
    Canvas(Modifier.fillMaxWidth().height(140.dp)) {
        val slot = size.width / 12f
        val bw = slot * 0.6f
        months.forEachIndexed { i, m ->
            val x = i * slot + (slot - bw) / 2
            val ht = size.height * (m.totalCents / max)
            val he = size.height * (m.eligibleCents / max)
            if (ht > 0) drawRoundRect(c.chartTotal, Offset(x, size.height - ht), Size(bw, ht), CornerRadius(6f))
            if (he > 0) drawRoundRect(c.chartMain, Offset(x, size.height - he), Size(bw, he), CornerRadius(6f))
        }
    }
    Row(Modifier.fillMaxWidth()) {
        months.forEach {
            Text(it.label.take(1), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
    }
    Legend()
}

@Composable
private fun Legend() {
    val c = LocalStatusColors.current
    Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
        LegendDot(c.chartTotal, stringResource(R.string.legend_total))
        LegendDot(c.chartMain, stringResource(R.string.legend_eligible))
    }
}

@Composable
private fun LegendDot(color: androidx.compose.ui.graphics.Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(Modifier.size(10.dp).background(color, RoundedCornerShape(3.dp)))
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun HBars(buckets: List<Bucket>) {
    if (buckets.isEmpty()) {
        Text("—", color = MaterialTheme.colorScheme.onSurfaceVariant)
        return
    }
    val c = LocalStatusColors.current
    val max = (buckets.maxOfOrNull { it.totalCents } ?: 0L).coerceAtLeast(1L).toFloat()
    buckets.forEach { b ->
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row {
                Text("${b.label} (${b.count})", modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.size(8.dp))
                Text(Format.euro(b.totalCents), fontWeight = FontWeight.SemiBold)
            }
            Canvas(Modifier.fillMaxWidth().height(8.dp)) {
                val r = CornerRadius(size.height / 2)
                drawRoundRect(c.chartTotal, size = Size(size.width * (b.totalCents / max).coerceAtLeast(0.01f), size.height), cornerRadius = r)
                if (b.eligibleCents > 0) drawRoundRect(c.chartMain, size = Size(size.width * (b.eligibleCents / max), size.height), cornerRadius = r)
            }
        }
    }
}

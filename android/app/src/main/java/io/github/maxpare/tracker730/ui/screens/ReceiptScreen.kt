// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import coil3.compose.AsyncImage
import io.github.maxpare.tracker730.AppContainer
import io.github.maxpare.tracker730.R
import io.github.maxpare.tracker730.data.Format
import io.github.maxpare.tracker730.data.Meta
import io.github.maxpare.tracker730.data.Profile
import io.github.maxpare.tracker730.data.ReceiptData
import io.github.maxpare.tracker730.data.ReceiptOut
import io.github.maxpare.tracker730.data.TaxCode
import io.github.maxpare.tracker730.ui.components.Banner
import io.github.maxpare.tracker730.ui.components.Chip
import io.github.maxpare.tracker730.ui.components.Dropdown
import io.github.maxpare.tracker730.ui.components.FormField
import io.github.maxpare.tracker730.ui.components.LoadingBox
import io.github.maxpare.tracker730.ui.components.SectionCard
import io.github.maxpare.tracker730.ui.components.SmallSpinner
import io.github.maxpare.tracker730.ui.components.Tone
import io.github.maxpare.tracker730.ui.components.toneForStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Editable text form mirroring [ReceiptData]; amounts and dates stay as typed until saved. */
data class ReceiptForm(
    val date: String = "",
    val amount: String = "",
    val deductible: String = "",
    val category: String? = null,
    val provider: String = "",
    val payment: String = "sconosciuto",
    val beneficiary: String = "self",
    val ssn: Boolean = false,
    val vat: String = "",
    val docNumber: String = "",
    val patientCf: String = "",
    val description: String = "",
    val tags: String = "",
    val notes: String = "",
) {
    /** Builds the payload; throws IllegalArgumentException with an Italian message if a field is invalid. */
    fun toData(base: ReceiptData, status: String): ReceiptData {
        val amountCents = Format.parseAmount(amount)
        var dedCents = Format.parseAmount(deductible)
        if (dedCents != null && dedCents == amountCents) dedCents = null
        return base.copy(
            status = status,
            date = Format.parseDate(date),
            amountCents = amountCents,
            deductibleCents = dedCents,
            category = category,
            providerName = provider.trim().ifBlank { null },
            paymentMethod = payment,
            beneficiary = beneficiary,
            ssnProvider = ssn,
            providerVat = vat.trim().ifBlank { null },
            documentNumber = docNumber.trim().ifBlank { null },
            patientTaxCode = patientCf.trim().uppercase().ifBlank { null },
            description = description.trim().ifBlank { null },
            tags = tags.split(',').map { it.trim() }.filter { it.isNotEmpty() },
            notes = notes.trim().ifBlank { null },
        )
    }

    companion object {
        fun from(d: ReceiptData) = ReceiptForm(
            date = Format.date(d.date),
            amount = Format.amountInput(d.amountCents),
            deductible = Format.amountInput(d.deductibleCents),
            category = d.category,
            provider = d.providerName.orEmpty(),
            payment = d.paymentMethod,
            beneficiary = d.beneficiary,
            ssn = d.ssnProvider,
            vat = d.providerVat.orEmpty(),
            docNumber = d.documentNumber.orEmpty(),
            patientCf = d.patientTaxCode.orEmpty(),
            description = d.description.orEmpty(),
            tags = d.tags.joinToString(", "),
            notes = d.notes.orEmpty(),
        )
    }
}

data class ReceiptState(
    val loading: Boolean = true,
    val receipt: ReceiptOut? = null,
    val form: ReceiptForm = ReceiptForm(),
    val saving: Boolean = false,
    val error: String? = null,
    val savedNotice: Boolean = false,
    val deleted: Boolean = false,
    val created: String? = null,
)

class ReceiptViewModel(private val c: AppContainer, private val id: String?) : ViewModel() {
    private val _state = MutableStateFlow(ReceiptState(loading = id != null))
    val state = _state.asStateFlow()

    init {
        if (id != null) load() else _state.update {
            it.copy(form = ReceiptForm(date = Format.date(java.time.LocalDate.now().toString())))
        }
    }

    fun load() = viewModelScope.launch {
        val rid = id ?: return@launch
        _state.update { it.copy(loading = true, error = null) }
        c.call { receipt(rid) }
            .onSuccess { r -> _state.update { it.copy(loading = false, receipt = r, form = ReceiptForm.from(r.data)) } }
            .onFailure { e -> _state.update { it.copy(loading = false, error = e.message) } }
    }

    fun edit(f: (ReceiptForm) -> ReceiptForm) = _state.update { it.copy(form = f(it.form), savedNotice = false) }

    fun save(status: String) = viewModelScope.launch {
        val s = _state.value
        val payload = try {
            s.form.toData(s.receipt?.data ?: ReceiptData(), status)
        } catch (e: IllegalArgumentException) {
            _state.update { it.copy(error = e.message) }
            return@launch
        }
        _state.update { it.copy(saving = true, error = null) }
        val result = if (id == null) c.call { createReceipt(payload) } else c.call { updateReceipt(id, payload) }
        result
            .onSuccess { r ->
                _state.update {
                    it.copy(saving = false, receipt = r, form = ReceiptForm.from(r.data), savedNotice = true,
                        created = if (id == null) r.id else null)
                }
            }
            .onFailure { e -> _state.update { it.copy(saving = false, error = e.message) } }
    }

    fun reprocess() = viewModelScope.launch {
        val rid = id ?: return@launch
        _state.update { it.copy(saving = true, error = null) }
        c.call { reprocess(rid) }
            .onSuccess { r -> _state.update { it.copy(saving = false, receipt = r, form = ReceiptForm.from(r.data)) } }
            .onFailure { e -> _state.update { it.copy(saving = false, error = e.message) } }
    }

    fun delete() = viewModelScope.launch {
        val rid = id ?: return@launch
        c.call { deleteReceipt(rid) }
            .onSuccess { _state.update { it.copy(deleted = true) } }
            .onFailure { e -> _state.update { it.copy(error = e.message) } }
    }

    fun imageUrl(kind: String): String? = id?.let { c.client?.fileUrl(it, kind) }
}

@Composable
fun ReceiptScreen(
    vm: ReceiptViewModel,
    meta: Meta?,
    profile: Profile,
    onClose: () -> Unit,
    onCreated: (String) -> Unit,
) {
    val st by vm.state.collectAsStateWithLifecycle()
    var confirmDelete by rememberSaveable { mutableStateOf(false) }
    var showOriginal by rememberSaveable { mutableStateOf(false) }
    var moreOpen by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(st.deleted) { if (st.deleted) onClose() }
    LaunchedEffect(st.created) { st.created?.let(onCreated) }

    if (st.loading) { LoadingBox(); return }
    val r = st.receipt
    if (r == null && st.error != null && vm.imageUrl("scan") != null) { RetryBox(st.error!!) { vm.load() }; return }
    val d = r?.data ?: ReceiptData(status = "verificato")
    val f = st.form
    val low = stringResource(R.string.low_confidence)
    val draft = d.status == "bozza"

    Column(
        Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                when {
                    r == null -> stringResource(R.string.receipt_new)
                    draft -> stringResource(R.string.receipt_review)
                    else -> d.providerName ?: stringResource(R.string.no_name)
                },
                style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f),
            )
            if (r != null) Chip(r.evaluation.label, toneForStatus(r.evaluation.status))
        }
        if (r != null && r.duplicates.isNotEmpty()) Banner(stringResource(R.string.duplicate_warning), Tone.Warn)

        if (r != null && (r.hasScan || r.originalType?.startsWith("image/") == true)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (r.hasScan) FilterChip(selected = !showOriginal, onClick = { showOriginal = false }, label = { Text(stringResource(R.string.receipt_scan)) })
                if (r.originalType?.startsWith("image/") == true) FilterChip(selected = showOriginal || !r.hasScan, onClick = { showOriginal = true }, label = { Text(stringResource(R.string.receipt_original)) })
            }
            AsyncImage(
                model = vm.imageUrl(if (showOriginal || !r.hasScan) "original" else "scan"),
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxWidth().heightIn(max = 520.dp).clip(RoundedCornerShape(10.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant),
            )
            if (r.originalType == "application/pdf") Text(stringResource(R.string.open_pdf), style = MaterialTheme.typography.bodySmall)
        }

        if (r != null && (r.evaluation.reasons.isNotEmpty() || r.evaluation.warnings.isNotEmpty())) {
            Banner("", when (r.evaluation.status) { "non_detraibile" -> Tone.Bad; "da_verificare" -> Tone.Warn; else -> Tone.Info },
                title = r.evaluation.label, lines = r.evaluation.reasons + r.evaluation.warnings)
        }
        if (draft && d.ocr?.warnings?.isNotEmpty() == true) {
            Banner("", Tone.Info, title = stringResource(R.string.ocr_notes), lines = d.ocr.warnings)
        }

        SectionCard {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FormField(f.date, { v -> vm.edit { it.copy(date = v) } }, stringResource(R.string.field_date), Modifier.weight(1f),
                    hint = stringResource(R.string.field_date_hint),
                    lowConfidence = d.isLowConfidence("date"), lowConfidenceText = low, keyboardType = KeyboardType.Number)
                FormField(f.amount, { v -> vm.edit { it.copy(amount = v) } }, stringResource(R.string.field_amount), Modifier.weight(1f),
                    lowConfidence = d.isLowConfidence("amount_cents"), lowConfidenceText = low, keyboardType = KeyboardType.Decimal)
            }
            Dropdown(
                stringResource(R.string.field_category),
                listOf<Pair<String?, String>>(null to stringResource(R.string.choose)) + (meta?.categories?.map { it.code to it.label } ?: emptyList()),
                f.category, { v -> vm.edit { it.copy(category = v) } },
                Modifier.fillMaxWidth(), lowConfidence = d.isLowConfidence("category"), lowConfidenceText = low,
            )
            meta?.categories?.firstOrNull { it.code == f.category }?.hint?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            FormField(f.provider, { v -> vm.edit { it.copy(provider = v) } }, stringResource(R.string.field_provider),
                lowConfidence = d.isLowConfidence("provider_name"), lowConfidenceText = low)
            Dropdown(
                stringResource(R.string.field_payment),
                meta?.paymentMethods?.map { it.code to it.label } ?: listOf(f.payment to f.payment),
                f.payment, { v -> vm.edit { it.copy(payment = v) } },
                Modifier.fillMaxWidth(), lowConfidence = d.isLowConfidence("payment_method"), lowConfidenceText = low,
            )
            Dropdown(
                stringResource(R.string.field_beneficiary), profile.beneficiaryOptions(), f.beneficiary,
                { v -> vm.edit { it.copy(beneficiary = v) } }, Modifier.fillMaxWidth(),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = f.ssn, onCheckedChange = { v -> vm.edit { it.copy(ssn = v) } })
                Column {
                    Text(stringResource(R.string.field_ssn))
                    Text(stringResource(R.string.field_ssn_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FormField(f.vat, { v -> vm.edit { it.copy(vat = v) } }, stringResource(R.string.field_vat), Modifier.weight(1f),
                    lowConfidence = d.isLowConfidence("provider_vat"), lowConfidenceText = low, keyboardType = KeyboardType.Number)
                FormField(f.docNumber, { v -> vm.edit { it.copy(docNumber = v) } }, stringResource(R.string.field_docnum), Modifier.weight(1f))
            }
            FormField(
                f.patientCf, { v -> vm.edit { it.copy(patientCf = v) } }, stringResource(R.string.field_patient_cf),
                hint = stringResource(R.string.field_patient_cf_hint), capitalizeCharacters = true,
                lowConfidence = d.isLowConfidence("patient_tax_code"), lowConfidenceText = low,
                isError = f.patientCf.isNotBlank() && !TaxCode.isValid(f.patientCf),
            )
            TextButton(onClick = { moreOpen = !moreOpen }) { Text(stringResource(R.string.more_details)) }
            AnimatedVisibility(moreOpen || f.deductible.isNotBlank() || f.notes.isNotBlank()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    FormField(f.deductible, { v -> vm.edit { it.copy(deductible = v) } }, stringResource(R.string.field_deductible),
                        hint = stringResource(R.string.field_deductible_hint), keyboardType = KeyboardType.Decimal)
                    FormField(f.description, { v -> vm.edit { it.copy(description = v) } }, stringResource(R.string.field_description))
                    FormField(f.tags, { v -> vm.edit { it.copy(tags = v) } }, stringResource(R.string.field_tags))
                    FormField(f.notes, { v -> vm.edit { it.copy(notes = v) } }, stringResource(R.string.field_notes), singleLine = false)
                }
            }
            st.error?.let { Banner(it, Tone.Bad) }
            if (st.savedNotice) Banner(stringResource(R.string.saved), Tone.Ok)
            Button(onClick = { vm.save("verificato") }, enabled = !st.saving, modifier = Modifier.fillMaxWidth()) {
                if (st.saving) SmallSpinner() else Text(stringResource(if (draft || r == null) R.string.confirm_save else R.string.save))
            }
            OutlinedButton(onClick = { vm.save("da_verificare") }, enabled = !st.saving, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.save_later))
            }
        }

        if (d.ocr != null && d.ocr.text.isNotBlank()) {
            SectionCard(title = stringResource(R.string.ocr_text)) {
                Text(
                    d.ocr.text, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(8.dp)).padding(8.dp),
                )
            }
        }
        if (r != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (r.hasOriginal) OutlinedButton(onClick = { vm.reprocess() }, enabled = !st.saving) { Text(stringResource(R.string.reprocess)) }
                TextButton(onClick = { confirmDelete = true }) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
            }
        }
    }

    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            text = { Text(stringResource(R.string.delete_receipt_q)) },
            confirmButton = { TextButton(onClick = { confirmDelete = false; vm.delete() }) { Text(stringResource(R.string.delete)) } },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

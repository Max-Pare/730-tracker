// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import io.github.maxpare.tracker730.ui.theme.LocalStatusColors

@Composable
fun SectionCard(modifier: Modifier = Modifier, title: String? = null, content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (title != null) Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            content()
        }
    }
}

enum class Tone { Ok, Warn, Bad, Info, Neutral }

fun toneForStatus(status: String): Tone = when (status) {
    "detraibile", "verificato" -> Tone.Ok
    "non_detraibile" -> Tone.Bad
    "da_verificare" -> Tone.Warn
    "bozza" -> Tone.Info
    else -> Tone.Neutral
}

@Composable
private fun toneColors(tone: Tone): Pair<Color, Color> {
    val s = LocalStatusColors.current
    return when (tone) {
        Tone.Ok -> s.ok to s.okBg
        Tone.Warn -> s.warn to s.warnBg
        Tone.Bad -> s.bad to s.badBg
        Tone.Info -> s.info to s.infoBg
        Tone.Neutral -> MaterialTheme.colorScheme.onSurfaceVariant to MaterialTheme.colorScheme.surfaceVariant
    }
}

@Composable
fun Chip(text: String, tone: Tone) {
    val (fg, bg) = toneColors(tone)
    Text(
        text,
        color = fg,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.background(bg, RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 3.dp),
    )
}

@Composable
fun Banner(text: String, tone: Tone, modifier: Modifier = Modifier, title: String? = null, lines: List<String> = emptyList()) {
    val (fg, bg) = toneColors(tone)
    Column(
        modifier.fillMaxWidth().background(bg, RoundedCornerShape(12.dp)).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        if (title != null) Text(title, color = fg, fontWeight = FontWeight.SemiBold)
        if (text.isNotEmpty()) Text(text, color = fg)
        lines.forEach { Text("• $it", color = fg, style = MaterialTheme.typography.bodyMedium) }
    }
}

@Composable
fun LoadingBox(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}

@Composable
fun FormField(
    value: String,
    onChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    hint: String? = null,
    lowConfidence: Boolean = false,
    lowConfidenceText: String? = null,
    keyboardType: KeyboardType = KeyboardType.Text,
    password: Boolean = false,
    singleLine: Boolean = true,
    isError: Boolean = false,
    capitalizeCharacters: Boolean = false,
) {
    val warn = LocalStatusColors.current.warn
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        modifier = modifier.fillMaxWidth(),
        singleLine = singleLine,
        minLines = if (singleLine) 1 else 3,
        isError = isError,
        visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(
            keyboardType = if (password) KeyboardType.Password else keyboardType,
            capitalization = if (capitalizeCharacters) androidx.compose.ui.text.input.KeyboardCapitalization.Characters
            else androidx.compose.ui.text.input.KeyboardCapitalization.None,
            autoCorrectEnabled = !password && keyboardType == KeyboardType.Text && !capitalizeCharacters,
        ),
        supportingText = when {
            lowConfidence && lowConfidenceText != null -> ({ Text(lowConfidenceText, color = warn) })
            hint != null -> ({ Text(hint) })
            else -> null
        },
        colors = if (lowConfidence) OutlinedTextFieldDefaults.colors(unfocusedBorderColor = warn, focusedBorderColor = warn) else OutlinedTextFieldDefaults.colors(),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun <T> Dropdown(
    label: String,
    options: List<Pair<T, String>>,
    selected: T,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    lowConfidence: Boolean = false,
    lowConfidenceText: String? = null,
) {
    var expanded by remember { mutableStateOf(false) }
    val warn = LocalStatusColors.current.warn
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }, modifier = modifier) {
        OutlinedTextField(
            value = options.firstOrNull { it.first == selected }?.second ?: "",
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            supportingText = if (lowConfidence && lowConfidenceText != null) ({ Text(lowConfidenceText, color = warn) }) else null,
            colors = if (lowConfidence) OutlinedTextFieldDefaults.colors(unfocusedBorderColor = warn) else OutlinedTextFieldDefaults.colors(),
            modifier = Modifier.menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            options.forEach { (value, text) ->
                DropdownMenuItem(text = { Text(text) }, onClick = { onSelect(value); expanded = false })
            }
        }
    }
}

@Composable
fun LabeledValue(label: String, value: String, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(8.dp))
        Text(value, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
fun SmallSpinner() = CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)

// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

private val Light = lightColorScheme(
    primary = Color(0xFF0F766E),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD5ECE9),
    onPrimaryContainer = Color(0xFF0B5E57),
    secondary = Color(0xFF4A635F),
    secondaryContainer = Color(0xFFD5ECE9),
    onSecondaryContainer = Color(0xFF0B5E57),
    background = Color(0xFFF5F6F4),
    onBackground = Color(0xFF1C2321),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF1C2321),
    surfaceVariant = Color(0xFFEEF1EF),
    onSurfaceVariant = Color(0xFF5D6865),
    surfaceContainer = Color(0xFFFFFFFF),
    surfaceContainerLow = Color(0xFFFFFFFF),
    outline = Color(0xFFC7CFCC),
    outlineVariant = Color(0xFFDFE4E1),
    error = Color(0xFFB42318),
)

private val Dark = darkColorScheme(
    primary = Color(0xFF3FB8AB),
    onPrimary = Color(0xFF08201D),
    primaryContainer = Color(0xFF163B37),
    onPrimaryContainer = Color(0xFF9FE3DA),
    secondary = Color(0xFFB1CCC7),
    secondaryContainer = Color(0xFF163B37),
    onSecondaryContainer = Color(0xFF9FE3DA),
    background = Color(0xFF111615),
    onBackground = Color(0xFFE6ECEA),
    surface = Color(0xFF1A2120),
    onSurface = Color(0xFFE6ECEA),
    surfaceVariant = Color(0xFF222B29),
    onSurfaceVariant = Color(0xFF9AA8A4),
    surfaceContainer = Color(0xFF1A2120),
    surfaceContainerLow = Color(0xFF1A2120),
    outline = Color(0xFF3A4744),
    outlineVariant = Color(0xFF2E3936),
    error = Color(0xFFFF8B7E),
)

/** Semantic colours for status chips and charts. */
@Immutable
data class StatusColors(
    val ok: Color, val okBg: Color,
    val warn: Color, val warnBg: Color,
    val bad: Color, val badBg: Color,
    val info: Color, val infoBg: Color,
    val chartTotal: Color, val chartMain: Color,
)

private val LightStatus = StatusColors(
    ok = Color(0xFF1D7A3E), okBg = Color(0xFFDCF1E2),
    warn = Color(0xFF9A5B00), warnBg = Color(0xFFFBEDD3),
    bad = Color(0xFFB42318), badBg = Color(0xFFFBE1DE),
    info = Color(0xFF2A5596), infoBg = Color(0xFFE3ECF8),
    chartTotal = Color(0xFFC8D6D3), chartMain = Color(0xFF0F766E),
)

private val DarkStatus = StatusColors(
    ok = Color(0xFF6FD391), okBg = Color(0xFF173322),
    warn = Color(0xFFF0B75A), warnBg = Color(0xFF3A2B10),
    bad = Color(0xFFFF8B7E), badBg = Color(0xFF3E1A16),
    info = Color(0xFF9CC0F5), infoBg = Color(0xFF1B2A40),
    chartTotal = Color(0xFF33413E), chartMain = Color(0xFF3FB8AB),
)

val LocalStatusColors = staticCompositionLocalOf { LightStatus }

@Composable
fun TrackerTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val scheme: ColorScheme = if (dark) Dark else Light
    androidx.compose.runtime.CompositionLocalProvider(LocalStatusColors provides if (dark) DarkStatus else LightStatus) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}

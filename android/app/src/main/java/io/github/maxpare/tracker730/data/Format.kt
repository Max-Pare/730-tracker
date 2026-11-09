// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.data

import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

/** Italian money/date formatting and parsing helpers (pure, unit-tested). */
object Format {
    private val dateIt = DateTimeFormatter.ofPattern("dd/MM/yyyy")
    private val dateTimeIt = DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm")

    /** 123456 -> "1.234,56" */
    fun cents(cents: Long?): String {
        if (cents == null) return ""
        val neg = cents < 0
        val abs = kotlin.math.abs(cents)
        val euros = (abs / 100).toString().reversed().chunked(3).joinToString(".").reversed()
        return (if (neg) "-" else "") + euros + "," + (abs % 100).toString().padStart(2, '0')
    }

    fun euro(cents: Long?): String = if (cents == null) "—" else "€ ${cents(cents)}"

    /** Value for an amount text field: 2340 -> "23,40". */
    fun amountInput(cents: Long?): String = if (cents == null) "" else "${cents / 100},${(cents % 100).toString().padStart(2, '0')}"

    /**
     * Parses what a user typed: "12,50", "1.234,56", "12.5", "€ 7", "1.234".
     * Returns null for blank input, throws [IllegalArgumentException] if invalid.
     */
    fun parseAmount(input: String?): Long? {
        var s = input?.trim()?.replace("€", "")?.replace("EUR", "", ignoreCase = true)?.replace(" ", "") ?: return null
        if (s.isEmpty()) return null
        val neg = s.startsWith("-")
        s = s.trimStart('+', '-')
        s = when {
            s.contains(',') -> s.replace(".", "").replace(',', '.')
            s.count { it == '.' } > 1 -> s.replace(".", "")
            s.contains('.') && s.substringAfter('.').length == 3 -> s.replace(".", "")
            else -> s
        }
        val value = s.toBigDecimalOrNull() ?: throw IllegalArgumentException("Importo non valido")
        val cents = value.multiply(BigDecimal(100)).setScale(0, RoundingMode.HALF_UP).toLong()
        return if (neg) -cents else cents
    }

    /** "2025-03-09" -> "09/03/2025" */
    fun date(iso: String?): String = try {
        if (iso.isNullOrBlank()) "" else LocalDate.parse(iso.take(10)).format(dateIt)
    } catch (_: DateTimeParseException) {
        iso ?: ""
    }

    /** "09/03/2025" or "9/3/25" or ISO -> "2025-03-09"; null if blank; throws if invalid. */
    fun parseDate(input: String?): String? {
        val s = input?.trim().orEmpty()
        if (s.isEmpty()) return null
        Regex("""^(\d{4})-(\d{1,2})-(\d{1,2})$""").matchEntire(s)?.let { m ->
            return LocalDate.of(m.groupValues[1].toInt(), m.groupValues[2].toInt(), m.groupValues[3].toInt()).toString()
        }
        val m = Regex("""^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})$""").matchEntire(s)
            ?: throw IllegalArgumentException("Data non valida")
        var y = m.groupValues[3].toInt()
        if (y < 100) y += 2000
        return try {
            LocalDate.of(y, m.groupValues[2].toInt(), m.groupValues[1].toInt()).toString()
        } catch (e: java.time.DateTimeException) {
            throw IllegalArgumentException("Data non valida")
        }
    }

    fun dateTime(iso: String?): String = try {
        if (iso.isNullOrBlank()) "" else OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault()).format(dateTimeIt)
    } catch (_: DateTimeParseException) {
        date(iso)
    }

    fun documents(n: Int): String = if (n == 1) "1 documento" else "$n documenti"
}

/** Codice fiscale check (same algorithm as the server) for instant feedback in forms. */
object TaxCode {
    private val odd = intArrayOf(1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23)
    private val pattern = Regex("^[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$")

    fun isValid(input: String?): Boolean {
        val cf = input?.trim()?.uppercase() ?: return false
        if (!pattern.matches(cf)) return false
        var sum = 0
        for (i in 0 until 15) {
            val c = cf[i]
            val idx = if (c.isDigit()) c - '0' else c - 'A'
            sum += if (i % 2 == 0) odd[idx] else idx
        }
        return cf[15] == 'A' + sum % 26
    }
}

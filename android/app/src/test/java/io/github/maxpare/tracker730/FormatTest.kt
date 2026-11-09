// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730

import io.github.maxpare.tracker730.data.Format
import io.github.maxpare.tracker730.data.TaxCode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FormatTest {
    @Test fun formatsCents() {
        assertEquals("1.234,56", Format.cents(123456))
        assertEquals("0,05", Format.cents(5))
        assertEquals("-12,00", Format.cents(-1200))
        assertEquals("1.000.000,00", Format.cents(100_000_000))
        assertEquals("€ 23,40", Format.euro(2340))
        assertEquals("—", Format.euro(null))
        assertEquals("23,40", Format.amountInput(2340))
    }

    @Test fun parsesAmounts() {
        assertEquals(1250L, Format.parseAmount("12,50"))
        assertEquals(123456L, Format.parseAmount("1.234,56"))
        assertEquals(1250L, Format.parseAmount("12.5"))
        assertEquals(700L, Format.parseAmount("€ 7"))
        assertEquals(123400L, Format.parseAmount("1.234"))
        assertNull(Format.parseAmount("  "))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsBadAmount() { Format.parseAmount("abc") }

    @Test fun dates() {
        assertEquals("09/03/2025", Format.date("2025-03-09"))
        assertEquals("2025-03-09", Format.parseDate("09/03/2025"))
        assertEquals("2025-03-09", Format.parseDate("9.3.25"))
        assertEquals("2025-03-09", Format.parseDate("2025-03-09"))
        assertNull(Format.parseDate(""))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsImpossibleDate() { Format.parseDate("31/02/2025") }

    @Test fun documents() {
        assertEquals("1 documento", Format.documents(1))
        assertEquals("3 documenti", Format.documents(3))
    }

    @Test fun taxCode() {
        assertTrue(TaxCode.isValid("RSSMRA80A01H501U"))
        assertTrue(TaxCode.isValid("rssmra80a01h501u"))
        assertFalse(TaxCode.isValid("RSSMRA80A01H501X"))
        assertFalse(TaxCode.isValid("123"))
    }
}

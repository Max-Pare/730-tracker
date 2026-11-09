// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730

import io.github.maxpare.tracker730.data.Dashboard
import io.github.maxpare.tracker730.data.Me
import io.github.maxpare.tracker730.data.Meta
import io.github.maxpare.tracker730.data.ReceiptPage
import io.github.maxpare.tracker730.data.ServerInfo
import io.github.maxpare.tracker730.data.SessionInfo
import io.github.maxpare.tracker730.data.TokenOut
import io.github.maxpare.tracker730.data.TrackerJson
import io.github.maxpare.tracker730.data.UploadResult
import io.github.maxpare.tracker730.data.parseErrorDetail
import io.github.maxpare.tracker730.ui.screens.ReceiptForm
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Fixtures are real responses recorded from the Python server (scripts/record_api_fixtures.py). */
class ApiContractTest {
    private fun fixture(name: String): String =
        requireNotNull(javaClass.classLoader?.getResource("fixtures/$name.json")) { name }.readText()

    @Test fun serverInfoAndMeta() {
        val info = TrackerJson.decodeFromString<ServerInfo>(fixture("server_info"))
        assertTrue(info.needsSetup)
        val meta = TrackerJson.decodeFromString<Meta>(fixture("meta"))
        assertTrue(meta.categories.any { it.code == "farmaci" && it.traceExempt })
        assertTrue(meta.paymentMethods.any { it.code == "tracciabile" })
    }

    @Test fun tokenAndMe() {
        val t = TrackerJson.decodeFromString<TokenOut>(fixture("token"))
        assertTrue(t.user.isAdmin)
        assertNotNull(t.recoveryCode)
        val me = TrackerJson.decodeFromString<Me>(fixture("me"))
        assertEquals("RSSMRA80A01H501U", me.profile.taxCode)
        assertEquals(2, me.profile.beneficiaryOptions().size)
    }

    @Test fun uploadResultWithOcrDraft() {
        val res = TrackerJson.decodeFromString<UploadResult>(fixture("upload"))
        assertEquals(1, res.created.size)
        assertEquals("x.jpg", res.errors.single().filename)
        val r = res.created.single()
        assertEquals("bozza", r.data.status)
        assertEquals(2340L, r.data.amountCents)
        assertEquals("self", r.data.beneficiary)
        assertTrue(r.hasScan)
        assertFalse(r.data.isLowConfidence("amount_cents"))
        assertTrue(r.data.ocr!!.text.contains("FARMACIA"))
    }

    @Test fun receiptsPageAndDashboard() {
        val page = TrackerJson.decodeFromString<ReceiptPage>(fixture("receipts"))
        assertEquals(2, page.total)
        val dash = TrackerJson.decodeFromString<Dashboard>(fixture("dashboard"))
        assertEquals(2025, dash.summary.year)
        assertEquals(12, dash.summary.byMonth.size)
        assertEquals(1, dash.draftsTotal)
        val sessions = TrackerJson.decodeFromString<List<SessionInfo>>(fixture("sessions"))
        assertTrue(sessions.any { it.current })
    }

    @Test fun errorBodies() {
        assertTrue(parseErrorDetail(fixture("error_login"))!!.startsWith("Nome utente o password"))
        assertNotNull(parseErrorDetail(fixture("error_validation")))
        assertEquals("boom", parseErrorDetail("""{"detail":"boom"}"""))
        assertNull(parseErrorDetail("<html>"))
    }

    @Test fun formRoundTripProducesServerPayload() {
        val r = TrackerJson.decodeFromString<UploadResult>(fixture("upload")).created.single()
        val form = ReceiptForm.from(r.data).copy(amount = "23,40", deductible = "20,00", tags = "farmacia, 2025 ")
        val data = form.toData(r.data, "verificato")
        assertEquals("verificato", data.status)
        assertEquals(2000L, data.deductibleCents)
        assertEquals(listOf("farmacia", "2025"), data.tags)
        assertEquals("2025-03-09", data.date)
        // Server ignores unknown keys; make sure the important ones are encoded.
        val json = TrackerJson.encodeToString(io.github.maxpare.tracker730.data.ReceiptData.serializer(), data)
        assertTrue(json.contains("\"amount_cents\":2340"))
        assertTrue(json.contains("\"payment_method\":\"tracciabile\""))
    }
}

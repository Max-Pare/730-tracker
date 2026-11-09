// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.ui

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import io.github.maxpare.tracker730.MainActivity
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Drives the real app UI (Robolectric) against a mock server that replays
 * responses recorded from the Python backend: setup → login → dashboard →
 * archive → receipt review.
 */
@OptIn(ExperimentalTestApi::class)
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35])
class AppFlowTest {
    @get:Rule val rule = createAndroidComposeRule<MainActivity>()

    private val server = MockWebServer()
    private val requests = mutableListOf<String>()

    private fun fixture(name: String) =
        requireNotNull(javaClass.classLoader?.getResource("fixtures/$name.json")) { name }.readText()

    @Before fun setUp() {
        val upload = io.github.maxpare.tracker730.data.TrackerJson.parseToJsonElement(fixture("upload"))
        val draft = (upload as kotlinx.serialization.json.JsonObject)["created"]!!.let { (it as kotlinx.serialization.json.JsonArray)[0] }
        val draftId = (draft as kotlinx.serialization.json.JsonObject)["id"].toString().trim('"')
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.path!!.substringBefore('?')
                synchronized(requests) { requests += "${request.method} $path" }
                val body = when {
                    path.endsWith("/api/v1/server-info") -> fixture("server_info").replace("\"needs_setup\": true", "\"needs_setup\": false")
                    path.endsWith("/api/v1/auth/login") -> fixture("token").replace("\"recovery_code\": \"ABCD-EFGH-JKMN-PQRS-TVWX-YZ23\"", "\"recovery_code\": null")
                    path.endsWith("/api/v1/me") -> fixture("me")
                    path.endsWith("/api/v1/meta") -> fixture("meta")
                    path.endsWith("/api/v1/dashboard") -> fixture("dashboard")
                    path.endsWith("/api/v1/receipts") -> fixture("receipts")
                    path.endsWith("/api/v1/receipts/$draftId") -> draft.toString()
                    else -> return MockResponse().setResponseCode(404).setBody("""{"detail":"not found"}""")
                }
                return MockResponse().setHeader("Content-Type", "application/json").setBody(body)
            }
        }
        server.start()
    }

    @After fun tearDown() = server.shutdown()

    /** Saves what the screen looks like to build/screenshots (handy when reviewing UI changes). */
    private fun snap(name: String) {
        rule.waitForIdle()
        val view = rule.activity.window.decorView
        val bmp = android.graphics.Bitmap.createBitmap(view.width, view.height, android.graphics.Bitmap.Config.ARGB_8888)
        view.draw(android.graphics.Canvas(bmp))
        val dir = java.io.File("build/screenshots").apply { mkdirs() }
        java.io.FileOutputStream(java.io.File(dir, "$name.png")).use { bmp.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun waitFor(text: String, substring: Boolean = false) =
        rule.waitUntil(15_000) { rule.onAllNodesWithText(text, substring = substring).fetchSemanticsNodes().isNotEmpty() }

    @Test fun setupLoginDashboardArchiveReview() {
        waitFor("Collega il tuo server")
        rule.onNode(hasSetTextAction() and hasText("Indirizzo del server")).performTextInput(server.url("/").toString())
        rule.onNodeWithText("Collega").performClick()

        waitFor("Accedi", substring = false)
        snap("01_login")
        rule.onNode(hasSetTextAction() and hasText("Nome utente")).performTextInput("mario")
        rule.onNode(hasSetTextAction() and hasText("Password")).performTextInput("password-lunga-1")
        rule.onNode(hasText("Accedi") and androidx.compose.ui.test.hasClickAction() and androidx.compose.ui.test.hasAnyAncestor(androidx.compose.ui.test.hasScrollAction()))
            .performScrollTo().performClick()

        // Dashboard with the recorded 2025 summary.
        waitFor("Detrazione stimata (19%)")
        waitFor("Spese 2025")
        snap("02_dashboard")
        assertTrue(synchronized(requests) { requests.any { it == "POST /api/v1/auth/login" } })

        // Archive lists both recorded receipts.
        rule.onNodeWithText("Archivio").performClick()
        waitFor("FARMACIA SAN MARCO DR. ROSSI")
        waitFor("Dott. Verdi")
        snap("03_archive")

        // Open the OCR draft: review form pre-filled with the extracted values.
        rule.onNodeWithText("FARMACIA SAN MARCO DR. ROSSI").performClick()
        waitFor("Controlla i dati")
        waitFor("23,40")
        waitFor("Conferma e salva")
        snap("04_review")
    }
}

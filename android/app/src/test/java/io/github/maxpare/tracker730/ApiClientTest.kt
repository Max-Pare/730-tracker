// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730

import io.github.maxpare.tracker730.data.ApiClient
import io.github.maxpare.tracker730.data.errorMessage
import io.github.maxpare.tracker730.data.normalizeServerUrl
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class ApiClientTest {
    private lateinit var server: MockWebServer
    private var unauthorized = 0

    @Before fun setUp() { server = MockWebServer().apply { start() } }
    @After fun tearDown() { server.shutdown() }

    private fun client(token: String?) = ApiClient(server.url("/tracker/"), { token }, { unauthorized++ })

    @Test fun normalizesUrls() {
        assertEquals("https://casa.example/", normalizeServerUrl("casa.example").toString())
        assertEquals("http://192.168.1.10:8000/", normalizeServerUrl("http://192.168.1.10:8000").toString())
        assertEquals("https://x.example/sub/", normalizeServerUrl(" https://x.example/sub?a=1 ").toString())
        assertNull(normalizeServerUrl(""))
    }

    @Test fun sendsBearerTokenAndRespectsSubpath() = runTest {
        server.enqueue(MockResponse().setBody("""{"name":"t","version":"1","api":1,"registration_mode":"invite","needs_setup":false}"""))
        client("abc.def").api.serverInfo()
        val req = server.takeRequest()
        assertEquals("/tracker/api/v1/server-info", req.path)
        assertEquals("Bearer abc.def", req.getHeader("Authorization"))
    }

    @Test fun reportsUnauthorizedAndReadableErrors() = runTest {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"Non autenticato."}"""))
        val e = runCatching { client("expired").api.me() }.exceptionOrNull()!!
        assertEquals(1, unauthorized)
        assertEquals("Non autenticato.", errorMessage(e))

        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":{"code":"weak_password","message":"Password corta"}}"""))
        val e2 = runCatching { client("t").api.changePassword(io.github.maxpare.tracker730.data.PasswordIn("a", "b")) }.exceptionOrNull()!!
        assertEquals("Password corta", errorMessage(e2))
        assertEquals(1, unauthorized)
    }

    @Test fun unitEndpointsAcceptNoContent() = runTest {
        server.enqueue(MockResponse().setResponseCode(204))
        client("t").api.deleteReceipt("abc")
        assertTrue(server.takeRequest().method == "DELETE")
    }

    @Test fun fileUrl() {
        assertTrue(client(null).fileUrl("r1", "scan").endsWith("/tracker/api/v1/receipts/r1/files/scan"))
    }
}

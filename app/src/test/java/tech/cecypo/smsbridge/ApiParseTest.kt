package tech.cecypo.smsbridge

import org.junit.Assert.*
import org.junit.Test

class ApiParseTest {
    private fun day(i: Int) = """{"date":"2026-11-${"%02d".format(i)}","matched":$i,"unmatched":0,"ignored":1,"duplicate":0,"error":0}"""
    private fun stats(last: String) =
        """{"message":{"daily":[${(1..14).joinToString(",") { day(it) }}],"unmatched_total":3,"last_posted_at":$last,
        "events":[{"time":"2026-11-09 10:00:00","sender":"MPESA","status":"Matched","entry":"SPR-0001","amount":1500.5},
        {"time":"2026-11-09 09:00:00","sender":"MPESA","status":"Unmatched","entry":null,"amount":null}]}}"""

    @Test fun parsesStatsFixture() {
        val s = Api.parseStats(stats("\"2026-11-09 10:00:00\""))
        assertEquals(14, s.daily.size)
        assertEquals(3, s.unmatchedTotal)
        assertEquals("2026-11-09 10:00:00", s.lastPostedAt)
        assertEquals(2, s.events.size)
        assertEquals(1500.5, s.events[0].amount!!, 0.0)
        assertNull(s.events[1].entry)
        assertNull(s.events[1].amount)
    }

    @Test fun nullLastPostedAt() = assertNull(Api.parseStats(stats("null")).lastPostedAt)

    @Test fun parsesConfig() {
        val c = Api.parseConfig("""{"message":{"enabled":true,"device":"d1","watched_senders":["DTB","MPESA"],"backfill_days":3}}""")
        assertTrue(c.enabled); assertEquals("d1", c.device); assertEquals(setOf("DTB", "MPESA"), c.watchedSenders); assertEquals(3, c.backfillDays)
    }

    @Test fun parsesUpload() {
        val r = Api.parseUpload("""{"message":{"results":[{"phone_sms_id":"5","status":"accepted","error":null},{"phone_sms_id":"6","status":"rejected","error":"body too long"}]}}""")
        assertEquals(listOf("5", "6"), r.map { it.phoneSmsId })
        assertEquals("rejected", r[1].status); assertEquals("body too long", r[1].error); assertNull(r[0].error)
    }

    private fun sms(id: Long) = Sms(id, "MPESA", "b", 1L, null)
    private fun res(vararg ids: Long) = ids.map { UploadResult("$it-1", "accepted", null) }

    @Test fun incompleteResultsThrow() {
        try { Api.verifyComplete(listOf(sms(5), sms(6)), res(5)); fail("expected ApiException") }
        catch (e: ApiException) { assertEquals("incomplete server response", e.message) }
    }

    @Test fun completeResultsPass() = Api.verifyComplete(listOf(sms(5), sms(6)), res(6, 5))

    @Test fun skipsUnparseableIds() {
        val r = Api.parseUpload("""{"message":{"results":[{"phone_sms_id":"","status":"rejected","error":"x"},{"phone_sms_id":"7","status":"accepted","error":null}]}}""")
        assertEquals(listOf("7"), r.map { it.phoneSmsId })
    }

    @Test fun errorTextFromServerMessages() = assertEquals("SMS device disabled",
        Api.errorText(403, """{"exc_type":"PermissionError","_server_messages":"[\"{\\\"message\\\": \\\"SMS device disabled\\\"}\"]"}"""))

    @Test fun errorTextFromException() = assertEquals("Not allowed",
        Api.errorText(403, """{"exception":"frappe.exceptions.PermissionError: Not allowed"}"""))

    @Test fun blankServerMessagesFallBackToException() = assertEquals("Not allowed",
        Api.errorText(403, """{"_server_messages":"[]","exception":"frappe.exceptions.PermissionError: Not allowed"}"""))

    @Test fun errorTextFallsBackToHttpCode() = assertEquals("HTTP 502", Api.errorText(502, "<html>bad gateway</html>"))
}

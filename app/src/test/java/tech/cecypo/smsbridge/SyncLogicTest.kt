package tech.cecypo.smsbridge

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class SyncLogicTest {
    private fun sms(id: Long, sender: String = "MPESA") = Sms(id, sender, "body $id", 1_700_000_000_000L + id, 1)
    private val rows = (5L..9L).map { sms(it) }

    @Test fun cursorUnchangedOnFailure() = assertEquals(4L, SyncLogic.nextCursor(rows, null, 4))

    @Test fun cursorSkipsUnwatched() =
        assertEquals(9L, SyncLogic.nextCursor((5L..9L).map { sms(it, "OTHER") }, emptyList(), 4))

    @Test fun rejectedCountsAsHandled() {
        val res = rows.map { UploadResult(it.key, if (it.id == 7L) "rejected" else "accepted", null) }
        assertEquals(9L, SyncLogic.nextCursor(rows, res, 4))
    }

    @Test fun cursorNeverMovesBackward() = assertEquals(20L, SyncLogic.nextCursor(rows, emptyList(), 20))

    @Test fun emptyScanKeepsCursor() = assertEquals(4L, SyncLogic.nextCursor(emptyList(), emptyList(), 4))

    @Test fun watchedIsCaseInsensitive() {
        val out = SyncLogic.watched(listOf(sms(1, "Mpesa"), sms(2, "Other")), setOf("MPESA"))
        assertEquals(listOf(1L), out.map { it.id })
    }

    @Test fun uploadJsonShape() {
        val o = JSONObject(SyncLogic.toUploadJson("dev-1", listOf(sms(5))))
        assertEquals("dev-1", o.getString("device_id"))
        val m = o.getJSONArray("messages").getJSONObject(0)
        assertEquals("5-1700000000005", m.get("phone_sms_id").toString())
        assertEquals("MPESA", m.getString("sender"))
        assertEquals("body 5", m.getString("body"))
        assertEquals(1_700_000_000_005L, m.getLong("received_at_ms"))
        assertEquals(1, m.getInt("sim_slot"))
    }

    @Test fun onlySamplesAreFlagged() {
        assertEquals(false, JSONObject(SyncLogic.toUploadJson("d", listOf(sms(5)))).getBoolean("sample"))
        assertEquals(true, JSONObject(SyncLogic.toUploadJson("d", listOf(sms(5)), sample = true)).getBoolean("sample"))
    }

    @Test fun nullSimSlotIsJsonNull() {
        val m = JSONObject(SyncLogic.toUploadJson("d", listOf(Sms(1, "A", "b", 1L, null)))).getJSONArray("messages").getJSONObject(0)
        assertTrue(m.has("sim_slot") && m.isNull("sim_slot"))
    }

    // _id reuse after the newest row was deleted: lower _id, newer date
    @Test fun reusedIdWithNewerDateIsNew() {
        val reused = Sms(5, "MPESA", "x", 2_000L, null)
        assertTrue(SyncLogic.isNew(reused, cursor = 9, maxDate = 1_000))
        assertEquals(listOf(reused), SyncLogic.fresh(listOf(reused), 9, 1_000))
    }

    @Test fun handledRowsAreNotNew() {
        val old = Sms(5, "MPESA", "x", 1_000L, null)
        assertFalse(SyncLogic.isNew(old, cursor = 9, maxDate = 1_000))
    }

    @Test fun unsetMaxDateUsesIdOnly() {
        assertTrue(SyncLogic.isNew(Sms(10, "A", "b", 1L, null), 9, -1))
        assertFalse(SyncLogic.isNew(Sms(5, "A", "b", 1L, null), 9, -1))
    }

    @Test fun rescanTerminates() {
        // after handling the reused row, cursor/maxDate cover everything re-read: loop must see nothing new
        val batch = listOf(Sms(5, "MPESA", "x", 2_000L, null), Sms(9, "MPESA", "y", 1_500L, null))
        val c = SyncLogic.nextCursor(batch, emptyList(), 9)
        val d = SyncLogic.nextMaxDate(batch, emptyList(), 1_000)
        assertEquals(9L, c); assertEquals(2_000L, d)
        assertTrue(SyncLogic.fresh(batch, c, d).isEmpty())
    }

    @Test fun maxDateUnchangedOnFailure() = assertEquals(1_000L, SyncLogic.nextMaxDate(rows, null, 1_000))

    @Test fun maxDateNeverMovesBackward() = assertEquals(Long.MAX_VALUE, SyncLogic.nextMaxDate(rows, emptyList(), Long.MAX_VALUE))

    @Test fun resendMovesCursorsBackOnly() {
        assertEquals(10L to 500L, SyncLogic.resendCursors(50, 900, 10, 500))
        assertEquals(50L to 900L, SyncLogic.resendCursors(50, 900, 70, 1_200))
    }

    @Test fun resendWithUnsetMaxDateUsesCutoff() = assertEquals(10L to 500L, SyncLogic.resendCursors(50, -1, 10, 500))

    @Test fun senderFilterIsCaseInsensitiveSubstring() {
        assertTrue(SyncLogic.senderMatches("MPESA", "pes"))
        assertTrue(SyncLogic.senderMatches("MPESA", " "))
        assertFalse(SyncLogic.senderMatches("MPESA", "kcb"))
    }

    @Test fun summarizeCounts() {
        val r = listOf("accepted", "duplicate", "rejected", "accepted").mapIndexed { i, s -> UploadResult("$i", s, null) }
        assertEquals(Triple(2, 1, 1), SyncLogic.summarize(r))
    }
}

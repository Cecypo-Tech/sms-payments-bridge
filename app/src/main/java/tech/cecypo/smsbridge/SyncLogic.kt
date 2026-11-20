package tech.cecypo.smsbridge

import org.json.JSONArray
import org.json.JSONObject

/** AOSP reuses an _id after the newest row is deleted, so the server key is "<_id>-<date ms>". */
data class Sms(val id: Long, val sender: String, val body: String, val dateMs: Long, val simSlot: Int?) {
    val key: String get() = "$id-$dateMs"
}
data class UploadResult(val phoneSmsId: String, val status: String, val error: String?)

object SyncLogic {
    fun watched(rows: List<Sms>, senders: Set<String>): List<Sms> = rows.filter { it.sender.uppercase() in senders }

    /** null results = upload failed -> stay put. Otherwise every scanned row was answered (accepted/duplicate/rejected) or unwatched. */
    @Suppress("UNUSED_PARAMETER")
    fun nextCursor(scanned: List<Sms>, results: List<UploadResult>?, current: Long): Long =
        if (results == null) current else maxOf(current, scanned.maxOfOrNull { it.id } ?: current)

    fun nextMaxDate(scanned: List<Sms>, results: List<UploadResult>?, current: Long): Long =
        if (results == null) current else maxOf(current, scanned.maxOfOrNull { it.dateMs } ?: current)

    /** Not yet handled: a higher _id, or (reused _id) a newer date. maxDate -1 = unset, _id only. */
    fun isNew(r: Sms, cursor: Long, maxDate: Long): Boolean = r.id > cursor || (maxDate >= 0 && r.dateMs > maxDate)

    fun fresh(rows: List<Sms>, cursor: Long, maxDate: Long): List<Sms> = rows.filter { isNew(it, cursor, maxDate) }

    /** Resend: only ever move the cursors back (never forward). maxDate -1 = unset, take the cutoff. */
    fun resendCursors(cursor: Long, maxDate: Long, backfillCursor: Long, cutoff: Long): Pair<Long, Long> =
        minOf(cursor, backfillCursor) to (if (maxDate < 0) cutoff else minOf(maxDate, cutoff))

    /** Sample picker filter: case-insensitive substring on the sender; blank matches all. */
    fun senderMatches(sender: String, filter: String): Boolean = sender.contains(filter.trim(), ignoreCase = true)

    /** accepted / duplicate / rejected (anything else counts as rejected). */
    fun summarize(results: List<UploadResult>): Triple<Int, Int, Int> {
        val a = results.count { it.status == "accepted" }
        val d = results.count { it.status == "duplicate" }
        return Triple(a, d, results.size - a - d)
    }

    /** [sample]: hand-picked in Send samples; the server logs these but never posts them on its own. */
    fun toUploadJson(deviceId: String, rows: List<Sms>, sample: Boolean = false): String = JSONObject()
        .put("device_id", deviceId)
        .put("sample", sample)
        .put("messages", JSONArray(rows.map {
            JSONObject()
                .put("phone_sms_id", it.key)
                .put("sender", it.sender)
                .put("body", it.body)
                .put("received_at_ms", it.dateMs)
                .put("sim_slot", it.simSlot ?: JSONObject.NULL)
        })).toString()
}

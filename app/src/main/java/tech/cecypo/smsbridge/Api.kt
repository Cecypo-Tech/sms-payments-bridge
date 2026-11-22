package tech.cecypo.smsbridge

import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import org.json.JSONArray
import org.json.JSONObject

data class Config(val enabled: Boolean, val device: String, val watchedSenders: Set<String>, val backfillDays: Int)
data class DayCount(val date: String, val matched: Int, val unmatched: Int, val ignored: Int, val duplicate: Int, val error: Int)
data class Event(val time: String, val sender: String, val status: String, val entry: String?, val amount: Double?)
data class Stats(val daily: List<DayCount>, val unmatchedTotal: Int, val lastPostedAt: String?, val events: List<Event>)
class ApiException(val httpCode: Int, message: String) : Exception(message)

class Api(private val baseUrl: String, private val key: String, private val secret: String) {
    private val prefix = "/api/method/sms_payments.sms_payments.api."

    fun getConfig(deviceId: String, deviceName: String, appVersion: String): Config =
        parseConfig(call("get_config", "device_id=${enc(deviceId)}&device_name=${enc(deviceName)}&app_version=${enc(appVersion)}", null))

    fun upload(deviceId: String, rows: List<Sms>, sample: Boolean = false): List<UploadResult> =
        parseUpload(call("upload", null, SyncLogic.toUploadJson(deviceId, rows, sample))).also { verifyComplete(rows, it) }

    fun stats(deviceId: String): Stats = parseStats(call("stats", "device_id=${enc(deviceId)}", null))

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    /** GET when body == null, else POST JSON. Returns the 2xx body; anything else throws ApiException. */
    private fun call(method: String, query: String?, body: String?): String {
        val conn = URL(baseUrl.trimEnd('/') + prefix + method + (query?.let { "?$it" } ?: "")).openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = 15_000
            conn.readTimeout = 15_000
            conn.setRequestProperty("Authorization", "token $key:$secret")
            conn.setRequestProperty("Accept", "application/json")
            if (body != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
            if (code !in 200..299) throw ApiException(code, errorText(code, text))
            return text
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        /** A 2xx answer must cover every uploaded row, else the cursor must not move. */
        internal fun verifyComplete(rows: List<Sms>, results: List<UploadResult>) {
            val got = results.map { it.phoneSmsId }.toSet()
            if (rows.any { it.key !in got }) throw ApiException(200, "incomplete server response")
        }

        /** Frappe error body -> readable text (_server_messages, else exception, else HTTP code). */
        internal fun errorText(code: Int, text: String): String {
            val o = try { JSONObject(text) } catch (e: Exception) { return "HTTP $code" }
            val fromMessages = try {
                val arr = JSONArray(o.optString("_server_messages"))
                (0 until arr.length()).joinToString("\n") { JSONObject(arr.getString(it)).optString("message") }
            } catch (e: Exception) { "" }
            if (fromMessages.isNotBlank()) return fromMessages
            return o.optString("exception").substringAfter(": ").ifBlank { "HTTP $code" }
        }

        private fun msg(json: String) = JSONObject(json).getJSONObject("message")
        private fun JSONObject.strOrNull(k: String) = if (isNull(k)) null else getString(k)

        fun parseConfig(json: String): Config {
            val m = msg(json)
            val s = m.getJSONArray("watched_senders")
            return Config(m.getBoolean("enabled"), m.getString("device"), (0 until s.length()).map { s.getString(it) }.toSet(), m.getInt("backfill_days"))
        }

        fun parseUpload(json: String): List<UploadResult> {
            val a = msg(json).getJSONArray("results")
            return (0 until a.length()).mapNotNull {
                val r = a.getJSONObject(it)
                val id = r.get("phone_sms_id").toString().ifBlank { return@mapNotNull null }
                UploadResult(id, r.getString("status"), r.strOrNull("error"))
            }
        }

        fun parseStats(json: String): Stats {
            val m = msg(json)
            val d = m.getJSONArray("daily")
            val e = m.getJSONArray("events")
            return Stats(
                (0 until d.length()).map { val r = d.getJSONObject(it); DayCount(r.getString("date"), r.getInt("matched"), r.getInt("unmatched"), r.getInt("ignored"), r.getInt("duplicate"), r.getInt("error")) },
                m.getInt("unmatched_total"),
                m.strOrNull("last_posted_at"),
                (0 until e.length()).map { val r = e.getJSONObject(it); Event(r.getString("time"), r.getString("sender"), r.getString("status"), r.strOrNull("entry"), if (r.isNull("amount")) null else r.getDouble("amount")) },
            )
        }
    }
}

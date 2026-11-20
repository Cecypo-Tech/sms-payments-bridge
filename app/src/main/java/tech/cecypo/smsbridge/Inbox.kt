package tech.cecypo.smsbridge

import android.content.Context
import android.database.sqlite.SQLiteException
import android.provider.Telephony

object Inbox {
    /** Rows with _id > afterId, or (when maxDate >= 0) date > maxDate to catch a reused _id. */
    fun readAfter(ctx: Context, afterId: Long, maxDate: Long, limit: Int = 100): List<Sms> {
        val base = arrayOf(Telephony.Sms._ID, Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE)
        return try {
            query(ctx, base + Telephony.Sms.SUBSCRIPTION_ID, afterId, maxDate, limit)
        } catch (e: IllegalArgumentException) {
            query(ctx, base, afterId, maxDate, limit)
        } catch (e: SQLiteException) {
            query(ctx, base, afterId, maxDate, limit)
        }
    }

    /** Newest [limit] inbox rows, any sender (for the sample picker). Same sub_id fallback as readAfter. */
    fun recent(ctx: Context, limit: Int): List<Sms> {
        val base = arrayOf(Telephony.Sms._ID, Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE)
        return try {
            query(ctx, base + Telephony.Sms.SUBSCRIPTION_ID, null, null, "date DESC LIMIT $limit")
        } catch (e: IllegalArgumentException) {
            query(ctx, base, null, null, "date DESC LIMIT $limit")
        } catch (e: SQLiteException) {
            query(ctx, base, null, null, "date DESC LIMIT $limit")
        }
    }

    private fun query(ctx: Context, cols: Array<String>, afterId: Long, maxDate: Long, limit: Int): List<Sms> {
        val sel = if (maxDate >= 0) "_id > ? OR date > ?" else "_id > ?"
        val args = if (maxDate >= 0) arrayOf(afterId.toString(), maxDate.toString()) else arrayOf(afterId.toString())
        return query(ctx, cols, sel, args, "_id ASC LIMIT $limit")
    }

    private fun query(ctx: Context, cols: Array<String>, sel: String?, args: Array<String>?, order: String): List<Sms> {
        val out = ArrayList<Sms>()
        ctx.contentResolver.query(Telephony.Sms.Inbox.CONTENT_URI, cols, sel, args, order)?.use { c ->
            while (c.moveToNext()) {
                out += Sms(
                    c.getLong(0), c.getString(1) ?: "", c.getString(2) ?: "", c.getLong(3),
                    if (cols.size > 4 && !c.isNull(4)) c.getInt(4).takeIf { it >= 0 } else null,
                )
            }
        }
        return out
    }

    /** Largest _id older than the cutoff, or 0. */
    fun cursorForBackfill(ctx: Context, days: Int): Long = backfillCutoff(days).let { cutoff ->
        ctx.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI, arrayOf(Telephony.Sms._ID), "date < ?", arrayOf(cutoff.toString()), "_id DESC LIMIT 1",
        )?.use { if (it.moveToFirst()) it.getLong(0) else 0L } ?: 0L
    }

    fun backfillCutoff(days: Int): Long = System.currentTimeMillis() - days * 86_400_000L
}

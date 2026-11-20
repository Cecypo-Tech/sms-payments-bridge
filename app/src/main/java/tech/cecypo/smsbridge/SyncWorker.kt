package tech.cecypo.smsbridge

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class SyncWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {
    override fun doWork(): Result {
        val prefs = Prefs(applicationContext)
        if (prefs.url.isBlank()) return Result.success()
        return try {
            sync(prefs)
        } catch (e: Exception) {
            // Cursor untouched. Never put credentials or SMS bodies in the message.
            prefs.lastError = (e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName).take(200)
            Result.retry()
        }
    }

    private fun sync(prefs: Prefs): Result {
        val api = Api(prefs.url, prefs.apiKey, prefs.apiSecret)
        val cfg = api.getConfig(prefs.deviceId, prefs.deviceName, (applicationContext.packageManager.getPackageInfo(applicationContext.packageName, 0).versionName ?: ""))
        prefs.senders = cfg.watchedSenders
        if (!cfg.enabled) {
            prefs.lastError = "Disabled on server"
            return Result.success()
        }
        if (prefs.cursor < 0) {
            prefs.cursor = Inbox.cursorForBackfill(applicationContext, cfg.backfillDays)
            prefs.maxDate = Inbox.backfillCutoff(cfg.backfillDays)
        }
        prefs.resendDays.takeIf { it > 0 }?.let { d ->
            val (c, m) = SyncLogic.resendCursors(prefs.cursor, prefs.maxDate, Inbox.cursorForBackfill(applicationContext, d), Inbox.backfillCutoff(d))
            prefs.cursor = c
            prefs.maxDate = m
            prefs.resendDays = 0
        }
        var rejected = 0
        while (true) {
            if (isStopped) return Result.retry()
            val rows = SyncLogic.fresh(Inbox.readAfter(applicationContext, prefs.cursor, prefs.maxDate), prefs.cursor, prefs.maxDate)
            if (rows.isEmpty()) break
            val watched = SyncLogic.watched(rows, cfg.watchedSenders)
            val results = if (watched.isEmpty()) emptyList() else api.upload(prefs.deviceId, watched)
            rejected += results.count { it.status == "rejected" }
            prefs.maxDate = SyncLogic.nextMaxDate(rows, results, prefs.maxDate)
            prefs.cursor = SyncLogic.nextCursor(rows, results, prefs.cursor)
        }
        prefs.lastSyncAt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())
        prefs.lastError = if (rejected > 0) "$rejected rejected by server" else ""
        return Result.success()
    }
}

/** Periodic trigger: only enqueues into the single "sync" chain so real syncs never run concurrently. */
class TickWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {
    override fun doWork(): Result { Sync.request(applicationContext); return Result.success() }
}

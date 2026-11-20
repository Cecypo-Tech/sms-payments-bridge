package tech.cecypo.smsbridge

import android.content.Context
import androidx.work.*
import java.util.concurrent.TimeUnit

object Sync {
    private val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /** delaySeconds lets the default SMS app write the inbox row before we read it. */
    fun request(ctx: Context, delaySeconds: Long = 0) {
        val req = OneTimeWorkRequestBuilder<SyncWorker>()
            .setInitialDelay(delaySeconds, TimeUnit.SECONDS)
            .setConstraints(online)
            .build()
        WorkManager.getInstance(ctx).enqueueUniqueWork("sync", ExistingWorkPolicy.APPEND_OR_REPLACE, req)
    }

    fun schedulePeriodic(ctx: Context) {
        val wm = WorkManager.getInstance(ctx)
        wm.cancelUniqueWork("sync-periodic") // old name: it synced directly and could race the "sync" chain
        val req = PeriodicWorkRequestBuilder<TickWorker>(15, TimeUnit.MINUTES).setConstraints(online).build()
        wm.enqueueUniquePeriodicWork("sync-tick", ExistingPeriodicWorkPolicy.KEEP, req)
    }
}

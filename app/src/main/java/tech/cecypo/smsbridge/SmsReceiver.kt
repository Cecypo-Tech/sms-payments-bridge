package tech.cecypo.smsbridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) = Sync.request(context, delaySeconds = 15)
}

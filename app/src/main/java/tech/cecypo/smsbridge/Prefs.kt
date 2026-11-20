package tech.cecypo.smsbridge

import android.content.Context
import android.content.SharedPreferences
import java.util.UUID

class Prefs(context: Context) {
    private val sp: SharedPreferences = context.getSharedPreferences("smsbridge", Context.MODE_PRIVATE)

    var url: String
        get() = sp.getString("url", "") ?: ""
        set(v) = sp.edit().putString("url", v).apply()
    var apiKey: String
        get() = sp.getString("apiKey", "") ?: ""
        set(v) = sp.edit().putString("apiKey", v).apply()
    var apiSecret: String
        get() = sp.getString("apiSecret", "") ?: ""
        set(v) = sp.edit().putString("apiSecret", v).apply()
    val deviceId: String
        @Synchronized get() = sp.getString("deviceId", null) ?: UUID.randomUUID().toString().also { sp.edit().putString("deviceId", it).apply() }
    var deviceName: String
        get() = sp.getString("deviceName", "") ?: ""
        set(v) = sp.edit().putString("deviceName", v).apply()
    /** -1 = not initialised */
    var cursor: Long
        get() = sp.getLong("cursor", -1L)
        set(v) = sp.edit().putLong("cursor", v).apply()
    /** max handled SMS date (ms), -1 = unset; second cursor that catches reused _ids */
    var maxDate: Long
        get() = sp.getLong("maxDate", -1L)
        set(v) = sp.edit().putLong("maxDate", v).apply()
    /** Days to resend; set by the UI, consumed by the next sync run (0 = none). */
    var resendDays: Int
        get() = sp.getInt("resendDays", 0)
        set(v) = sp.edit().putInt("resendDays", v).apply()
    var senders: Set<String>
        get() = sp.getStringSet("senders", emptySet()) ?: emptySet()
        set(v) = sp.edit().putStringSet("senders", v).apply()
    var lastSyncAt: String
        get() = sp.getString("lastSyncAt", "") ?: ""
        set(v) = sp.edit().putString("lastSyncAt", v).apply()
    var lastError: String
        get() = sp.getString("lastError", "") ?: ""
        set(v) = sp.edit().putString("lastError", v).apply()
    var autostartDone: Boolean
        get() = sp.getBoolean("autostartDone", false)
        set(v) = sp.edit().putBoolean("autostartDone", v).apply()
    var disclosureAccepted: Boolean
        get() = sp.getBoolean("disclosureAccepted", false)
        set(v) = sp.edit().putBoolean("disclosureAccepted", v).apply()
}

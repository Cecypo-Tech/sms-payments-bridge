package tech.cecypo.smsbridge

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.StyleSpan
import android.graphics.Typeface
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

class MainActivity : AppCompatActivity() {
    private enum class Screen { SETUP, DISCLOSURE, CHECKLIST, HOME, PICKER }

    private lateinit var prefs: Prefs
    private var screen = Screen.SETUP
    private var smsBlocked = false // permission refused for good, or blocked as restricted (Android 13+)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        prefs = Prefs(this)
        onBackPressedDispatcher.addCallback(this, object : androidx.activity.OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (screen == Screen.PICKER) show(Screen.HOME) else if (screen == Screen.SETUP && prefs.url.isNotBlank()) route() else { isEnabled = false; onBackPressedDispatcher.onBackPressed(); isEnabled = true }
            }
        })
        route()
    }

    override fun onResume() {
        super.onResume()
        // Coming back from a system settings screen: redraw the ticks.
        if (screen == Screen.CHECKLIST) route()
        if (prefs.url.isNotBlank()) {
            Sync.request(this)
            Sync.schedulePeriodic(this)
        }
    }

    private fun smsGranted() =
        checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED

    private fun batteryOk() = (getSystemService(POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(packageName)

    private fun route() {
        when {
            prefs.url.isBlank() -> show(Screen.SETUP)
            !prefs.disclosureAccepted -> show(Screen.DISCLOSURE)
            !smsGranted() || !batteryOk() -> show(Screen.CHECKLIST)
            else -> show(Screen.HOME)
        }
    }

    private fun show(s: Screen) {
        screen = s
        when (s) {
            Screen.SETUP -> showSetup()
            Screen.DISCLOSURE -> showDisclosure()
            Screen.CHECKLIST -> showChecklist()
            Screen.HOME -> showHome()
            Screen.PICKER -> showPicker()
        }
        invalidateOptionsMenu()
    }

    /** Every screen goes through here: toolbar on top, content below, system-bar and keyboard insets applied once. */
    private fun setScreen(layoutId: Int) {
        setContentView(R.layout.screen)
        layoutInflater.inflate(layoutId, findViewById<android.widget.FrameLayout>(R.id.content))
        setSupportActionBar(findViewById<Toolbar>(R.id.toolbar))
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = false
            isAppearanceLightNavigationBars = false
        }
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.screenRoot)) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            insets
        }
        ViewCompat.requestApplyInsets(findViewById(R.id.screenRoot))
    }

    private fun bg(work: () -> Unit) { Thread(work).start() }
    private fun ui(f: () -> Unit) = runOnUiThread { if (!isFinishing && !isDestroyed) f() }

    // ---- Setup ----

    private fun showSetup() {
        setScreen(R.layout.setup)
        title = "Setup"
        val url = findViewById<EditText>(R.id.url)
        val key = findViewById<EditText>(R.id.apiKey)
        val secret = findViewById<EditText>(R.id.apiSecret)
        val name = findViewById<EditText>(R.id.deviceName)
        val msg = findViewById<TextView>(R.id.setupMsg)
        val test = findViewById<Button>(R.id.test)
        val normal = msg.textColors // captured before any error colour is set
        url.setText(prefs.url)
        key.setText(prefs.apiKey)
        secret.setText(prefs.apiSecret) // textPassword: shown masked
        name.setText(prefs.deviceName.ifBlank { Build.MANUFACTURER + " " + Build.MODEL })
        test.setOnClickListener {
            val raw = url.text.toString().trim().trimEnd('/')
            val u = if ("://" in raw) raw else "https://$raw"
            val k = key.text.toString().trim()
            val sec = secret.text.toString().trim()
            val n = name.text.toString().trim().ifBlank { Build.MANUFACTURER + " " + Build.MODEL }
            fun fail(t: String) { msg.setTextColor(getColor(R.color.error)); msg.text = t }
            if (!u.startsWith("https://", ignoreCase = true) || u.length <= 8) { fail("The URL must start with https://"); return@setOnClickListener }
            if (k.isEmpty() || sec.isEmpty()) { fail("Enter the API key and secret"); return@setOnClickListener }
            test.isEnabled = false
            msg.setTextColor(normal)
            msg.text = "Connecting…"
            bg {
                val err = try {
                    val version = packageManager.getPackageInfo(packageName, 0).versionName ?: ""
                    Api(u, k, sec).getConfig(prefs.deviceId, n, version)
                    null
                } catch (_: java.net.UnknownHostException) {
                    "Cannot reach that address. Check the address and your internet."
                } catch (_: java.net.ConnectException) {
                    "Cannot reach that address. Check the address and your internet."
                } catch (e: ApiException) {
                    if (e.httpCode == 401 || e.httpCode == 403) "ERPNext did not accept the API key or secret."
                    else e.message?.takeIf { it.isNotBlank() } ?: "HTTP ${e.httpCode}"
                } catch (e: Exception) {
                    e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName
                }
                ui {
                    test.isEnabled = true
                    if (err != null) fail(err) else {
                        if (Uri.parse(u).host != Uri.parse(prefs.url).host) prefs.disclosureAccepted = false
                        prefs.url = u; prefs.apiKey = k; prefs.apiSecret = sec; prefs.deviceName = n
                        route()
                    }
                }
            }
        }
    }

    // ---- Disclosure ----

    private fun showDisclosure() {
        setScreen(R.layout.disclosure)
        title = "Before you continue"
        val head = getString(R.string.disclosure_head)
        val text = SpannableStringBuilder(head).append(" ").append(getString(R.string.disclosure_body, prefs.url))
        text.setSpan(StyleSpan(Typeface.BOLD), 0, head.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        findViewById<TextView>(R.id.disclosureText).text = text
        findViewById<Button>(R.id.agree).setOnClickListener { prefs.disclosureAccepted = true; route() }
        findViewById<Button>(R.id.cancel).setOnClickListener { show(Screen.SETUP) }
    }

    // ---- Checklist ----

    private fun tick(id: Int, ok: Boolean) {
        findViewById<TextView>(id).text = if (ok) "✓" else "○"
    }

    private fun showChecklist() {
        setScreen(R.layout.checklist)
        title = "Checklist"
        val sms = smsGranted()
        val battery = batteryOk()
        tick(R.id.tickSms, sms); tick(R.id.tickBattery, battery); tick(R.id.tickAuto, prefs.autostartDone)

        val smsBtn = findViewById<Button>(R.id.btnSms)
        val smsNote = findViewById<TextView>(R.id.noteSms)
        smsBtn.isEnabled = prefs.disclosureAccepted
        smsBtn.visibility = if (sms) View.GONE else View.VISIBLE
        if (smsBlocked && !sms) {
            smsNote.text = getString(R.string.sms_blocked_help)
            smsBtn.text = "Open App info"
            smsBtn.setOnClickListener { smsBlocked = false; openAppInfo() }
        } else {
            smsBtn.text = "Allow SMS access"
            smsBtn.setOnClickListener {
                requestPermissions(arrayOf(Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS), REQ_SMS)
            }
        }

        val batBtn = findViewById<Button>(R.id.btnBattery)
        batBtn.text = "Allow background activity"
        batBtn.visibility = if (battery) View.GONE else View.VISIBLE
        batBtn.setOnClickListener {
            tryStart(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")),
                Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
            )
        }

        findViewById<Button>(R.id.btnAuto).apply {
            text = "Open autostart settings"
            setOnClickListener { openAutostart() }
        }
        findViewById<CheckBox>(R.id.autoDone).apply {
            isChecked = prefs.autostartDone
            setOnCheckedChangeListener { _, c -> prefs.autostartDone = c; tick(R.id.tickAuto, c) }
        }

        findViewById<Button>(R.id.cont).apply {
            isEnabled = sms && battery
            setOnClickListener { route() }
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_SMS) return
        // Not granted and no rationale to show = refused for good or restricted: never leave the user with a dead button.
        smsBlocked = !smsGranted() // a sideloaded app is refused as restricted until App info allows it
        if (screen == Screen.CHECKLIST) route()
    }

    private fun openAppInfo() = tryStart(
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")),
    )

    private fun openAutostart() {
        val known = listOf(
            "com.miui.securitycenter" to "com.miui.permcenter.autostart.AutoStartManagementActivity",
            "com.transsion.phonemaster" to "com.cyin.himgr.autostart.AutoStartActivity",
            "com.samsung.android.lool" to "com.samsung.android.sm.ui.battery.BatteryActivity",
        )
        for ((pkg, cls) in known) {
            val i = Intent().setComponent(ComponentName(pkg, cls))
            if (i.resolveActivity(packageManager) != null && tryStart(i)) return
        }
        openAppInfo()
    }

    /** Starts the first intent that works; true on success. Never throws. */
    private fun tryStart(vararg intents: Intent): Boolean {
        for (i in intents) {
            try { startActivity(i); return true } catch (_: Exception) { /* try next */ }
        }
        Toast.makeText(this, "Could not open that settings screen. Open Settings > Apps > SMS Payments Bridge.", Toast.LENGTH_LONG).show()
        return false
    }

    // ---- Home ----

    private fun showHome() {
        setScreen(R.layout.home)
        title = "SMS Payments Bridge"
        val refresh = findViewById<SwipeRefreshLayout>(R.id.refresh)
        refresh.setOnRefreshListener {
            Sync.request(this)
            loadStats(refresh)
        }
        renderStatus()
        refresh.isRefreshing = true
        loadStats(refresh)
    }

    private fun renderStatus() {
        val last = prefs.lastSyncAt
        val today = java.time.LocalDate.now().toString() // yyyy-MM-dd, same calendar and zone as lastSyncAt
        findViewById<TextView>(R.id.status).text = when {
            last.length < 16 -> "Not synced yet"
            last.startsWith(today) -> "Last sync ${last.substring(11, 16)}"
            else -> "Last sync ${last.substring(0, 16)}"
        }
        findViewById<TextView>(R.id.errorLine).apply {
            val e = prefs.lastError
            visibility = if (e.isBlank()) View.GONE else View.VISIBLE
            text = e
            setTextColor(getColor(R.color.error))
        }
    }

    // Server times are "yyyy-MM-dd HH:mm:ss": the time alone for today, day and time before that.
    private fun shortTime(ts: String?): String = try {
        val t = java.time.LocalDateTime.parse(ts!!.take(19).replace(' ', 'T'))
        t.format(java.time.format.DateTimeFormatter.ofPattern(if (t.toLocalDate() == java.time.LocalDate.now()) "HH:mm" else "d MMM HH:mm"))
    } catch (e: Exception) {
        ts ?: "—"
    }

    private fun loadStats(refresh: SwipeRefreshLayout) {
        bg {
            val res = try {
                Api(prefs.url, prefs.apiKey, prefs.apiSecret).stats(prefs.deviceId) to null
            } catch (e: Exception) {
                null to (e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName)
            }
            ui {
                if (screen != Screen.HOME) return@ui
                refresh.isRefreshing = false
                renderStatus()
                val (stats, err) = res
                if (stats == null) {
                    findViewById<TextView>(R.id.errorLine).apply {
                        visibility = View.VISIBLE
                        text = listOf(prefs.lastError, err).filter { !it.isNullOrBlank() }.joinToString("\n")
                    }
                    return@ui
                }
                findViewById<TextView>(R.id.unmatched).text = stats.unmatchedTotal.toString()
                findViewById<TextView>(R.id.lastPosted).text = "Last posted: ${shortTime(stats.lastPostedAt)}"
                findViewById<BarChartView>(R.id.chart).setData(stats.daily)
                val box = findViewById<android.widget.LinearLayout>(R.id.events)
                box.removeAllViews()
                stats.events.take(50).forEach { ev ->
                    val row = layoutInflater.inflate(R.layout.event_row, box, false)
                    row.findViewById<TextView>(R.id.evTop).text = "${shortTime(ev.time)}  ${ev.sender}"
                    row.findViewById<TextView>(R.id.evSub).text =
                        listOfNotNull(ev.status, ev.amount?.let { "%,.2f".format(it) }, ev.entry).joinToString(" · ")
                    box.addView(row)
                }
                if (stats.events.isEmpty()) box.addView(TextView(this).apply { text = "No messages yet" })
            }
        }
    }

    // ---- Sample picker ----
    // Samples never touch cursor, maxDate or resendDays: they go straight through Api.upload,
    // flagged as samples so ERPNext never posts them as payments on its own.

    private var pickRows: List<Sms> = emptyList()
    private val picked = LinkedHashSet<String>() // Sms.key, survives filtering
    private var pickSending = false // true while a send is in flight: checkbox toggles must not re-enable Send

    private fun openPicker() {
        if (prefs.url.isBlank() || !prefs.disclosureAccepted || !smsGranted()) {
            Toast.makeText(this, "Finish setup and allow SMS access first.", Toast.LENGTH_LONG).show()
            return
        }
        show(Screen.PICKER)
    }

    private fun showPicker() {
        setScreen(R.layout.sample_picker)
        title = "Send samples"
        picked.clear()
        pickSending = false
        val filter = findViewById<EditText>(R.id.senderFilter)
        val box = findViewById<android.widget.LinearLayout>(R.id.pickList)
        val send = findViewById<Button>(R.id.sendSamples)
        val watched = prefs.senders
        val fmt = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", java.util.Locale.getDefault())
        pickRows = try { Inbox.recent(this, PICK_LIMIT) } catch (e: Exception) {
            Toast.makeText(this, "Could not read SMS: ${e.message ?: e.javaClass.simpleName}", Toast.LENGTH_LONG).show(); emptyList()
        }
        fun refreshButton() {
            send.isEnabled = picked.isNotEmpty() && !pickSending
            send.text = when (picked.size) {
                0 -> "Tick messages to send"
                1 -> "Send 1 sample"
                else -> "Send ${picked.size} samples"
            }
        }
        findViewById<TextView>(R.id.pickEmpty).visibility = if (pickRows.isEmpty()) View.VISIBLE else View.GONE
        val views = pickRows.map { sms ->
            val row = layoutInflater.inflate(R.layout.sample_row, box, false)
            row.findViewById<TextView>(R.id.pickSender).text = sms.sender
            row.findViewById<TextView>(R.id.pickWatched).visibility = if (sms.sender.uppercase() in watched) View.VISIBLE else View.GONE
            row.findViewById<TextView>(R.id.pickDate).text = fmt.format(java.util.Date(sms.dateMs))
            row.findViewById<TextView>(R.id.pickBody).text = sms.body
            row.findViewById<CheckBox>(R.id.pickCheck).setOnCheckedChangeListener { _, c ->
                if (c) picked.add(sms.key) else picked.remove(sms.key)
                refreshButton()
            }
            row.setOnClickListener { row.findViewById<CheckBox>(R.id.pickCheck).toggle() }
            box.addView(row)
            row
        }
        filter.addTextChangedListener(object : android.text.TextWatcher {
            override fun afterTextChanged(s: android.text.Editable?) {
                val f = s?.toString() ?: ""
                pickRows.forEachIndexed { i, sms -> views[i].visibility = if (SyncLogic.senderMatches(sms.sender, f)) View.VISIBLE else View.GONE }
            }
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
        })
        refreshButton()
        send.setOnClickListener {
            val chosen = pickRows.filter { it.key in picked }
            val hidden = pickRows.indices.count { pickRows[it].key in picked && views[it].visibility != View.VISIBLE }
            val note = if (hidden > 0) " ($hidden hidden by the filter)" else ""
            AlertDialog.Builder(this)
                .setMessage("Send ${chosen.size} ${if (chosen.size == 1) "message" else "messages"}$note to ${prefs.url}?")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Send") { _, _ -> sendSamples(chosen, views, send) }
                .show()
        }
    }

    private fun sendSamples(chosen: List<Sms>, views: List<View>, send: Button) {
        pickSending = true
        send.isEnabled = false
        val api = Api(prefs.url, prefs.apiKey, prefs.apiSecret)
        val deviceId = prefs.deviceId
        bg {
            val results = ArrayList<UploadResult>()
            var err: String? = null
            try {
                chosen.chunked(100).forEach { results += api.upload(deviceId, it, sample = true) }
            } catch (e: Exception) {
                err = e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName
            }
            val (a, d, r) = SyncLogic.summarize(results)
            ui {
                pickSending = false
                val summary = "$a accepted, $d duplicate, $r rejected"
                if (err == null && screen == Screen.PICKER) {
                    picked.clear()
                    views.forEach { it.findViewById<CheckBox>(R.id.pickCheck).isChecked = false }
                }
                if (screen == Screen.PICKER) send.isEnabled = picked.isNotEmpty()
                AlertDialog.Builder(this)
                    .setTitle(if (err == null) "Samples sent" else "Send failed")
                    .setMessage(if (err == null) summary else "$err\n\nBefore the failure: $summary")
                    .setPositiveButton("OK", null)
                    .show()
            }
        }
    }

    // ---- Menu ----

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        if (screen == Screen.HOME) {
            menu.add(0, MENU_EDIT, 0, "Edit connection")
            menu.add(0, MENU_RESEND, 1, "Resend recent messages")
            menu.add(0, MENU_SAMPLES, 2, "Send samples")
        }
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean = when (item.itemId) {
        MENU_EDIT -> { show(Screen.SETUP); true } // cursor is kept
        MENU_RESEND -> { askResend(); true }
        MENU_SAMPLES -> { openPicker(); true }
        else -> super.onOptionsItemSelected(item)
    }

    private fun askResend() {
        val input = EditText(this).apply { inputType = InputType.TYPE_CLASS_NUMBER; setText("3") }
        val dlg = AlertDialog.Builder(this)
            .setTitle("Resend recent messages")
            .setMessage("Days (1–60). The server skips messages it already has.")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Resend", null)
            .create()
        val dp = resources.displayMetrics.density
        dlg.setView(input, (24 * dp).toInt(), (8 * dp).toInt(), (24 * dp).toInt(), 0)
        dlg.setOnShowListener { dlg.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val days = input.text.toString().toIntOrNull()
            if (days == null || days !in 1..60) { input.error = "Enter a number from 1 to 60"; return@setOnClickListener }
            prefs.resendDays = days // the sync worker applies it, so a running sync can't undo it
            Sync.request(this)
            Toast.makeText(this, "Resending last $days days", Toast.LENGTH_SHORT).show()
            dlg.dismiss()
        } }
        dlg.show()
    }

    private companion object {
        const val REQ_SMS = 1
        const val MENU_EDIT = 1
        const val MENU_RESEND = 2
        const val MENU_SAMPLES = 3
        const val PICK_LIMIT = 200
    }
}

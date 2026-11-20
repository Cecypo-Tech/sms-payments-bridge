# SMS Payments Bridge (Android) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A sideloadable Android app that forwards SMS from the senders ERPNext watches to the SMS Payments endpoints, and shows the daily chart, the unmatched count, the last posted entry and an event log.

**Architecture:** One `MainActivity` that switches between three views: Setup, Checklist and Home. The phone's SMS inbox is the queue. A saved `_id` cursor plus a saved max-`date` cursor (Android reuses an `_id` after the newest row is deleted, so a row also counts as new when its date is newer) track how far forwarding has got, and a WorkManager `SyncWorker` reads rows past that cursor, uploads them in batches of 100, and moves the cursor forward only after the server answers. Sync triggers are the SMS broadcast, a 15-minute periodic job, boot, and app open. There is no local database and no rule logic on the phone.

**Tech Stack:** GitHub Actions (`actions/setup-java@v4` Temurin 17, `gradle/actions/setup-gradle@v4` with `gradle-version: 8.11.1`, no wrapper committed), Kotlin 2.1.21, Android Gradle Plugin 8.10.1 (needs Gradle 8.11.1; if CI says compileSdk 36 is unsupported, move to the newest AGP 8.x patch and the Gradle version it names), compileSdk/targetSdk 36, minSdk 26, AndroidX core-ktx, appcompat, WorkManager 2.10.0 and swiperefreshlayout. HTTP uses `HttpURLConnection` and JSON uses `org.json` (both built into Android). Tests are plain JUnit 4.

**Spec:** `~/frappe-bench/apps/cecypo_bank_integrations/artifacts/superpowers/2026-11-09-sms-payment-register-design.md` §5. **API contract:** Task 5 of `2026-11-09-sms-payments-frappe-plan.md` (same directory). Read both before starting.

**Depends on:** Start this plan only after Frappe plan Task 7 Step 3 has proven the rules on the user's real SMS, pasted in with Add SMS manually. Its notes are in `2026-11-09-sms-payments-rules-pilot.md`.

**Distribution:** for now, a signed APK installed directly ("unknown sources"). The user decided this. Play registration and a listing come later under Cecypo's Google Play **organisation** account (spec §8) and are not part of this plan. This plan only keeps that door open: a stable package ID and signing key, targetSdk 36, and the disclosure screen in Task 4.

**Builds run in GitHub Actions only.** Nothing Android-related is installed on this machine: no JDK, no SDK, no Gradle. Every push runs unit tests and builds the signed APK, and the APK is downloaded from the run's artifacts. Unit tests run in CI, not locally.

## Global Constraints

- App name **SMS Payments Bridge**, package `tech.cecypo.smsbridge`, repo `Cecypo-Tech/sms-payments-bridge` (private; the user approved creating it), local path `~/sms-payments-bridge`.
- The URL must be HTTPS. Setup refuses `http://`.
- `android:allowBackup="false"`. Credentials live in private `SharedPreferences` and are never logged.
- Signing key: a PKCS12 keystore made with `openssl` (no Java needed), kept at `~/.android-keys/sms-payments-bridge.p12`. It reaches CI only as repo secrets: `SIGNING_KEYSTORE_B64` and `SIGNING_PASSWORD`, with alias `smsbridge`. The keystore never goes into git. Losing it means phones can't update the app in place, so the user keeps a backup copy.
- Every request: connect and read timeouts of 15 s, header `Authorization: token <key>:<secret>`, and `Accept: application/json`.
- Only SMS whose sender (uppercased) is in `watched_senders` are ever put into an upload.
- Each commit message has no `Co-Authored-By` trailer.
- No libraries beyond the Tech Stack list.

## Review Focus

1. **A new SMS arrives while a sync is running.** It must still be uploaded. The unique work uses `ExistingWorkPolicy.APPEND_OR_REPLACE`, so a second sync runs after the current one (Task 3 manual check, plus a code-review point).
2. **The server is down or there is no signal during a batch.** The cursor must not move, and the next sync must resend the same rows (`SyncLogicTest.cursorUnchangedOnFailure`).
3. **A batch contains only unwatched senders.** The cursor must still move past them, otherwise sync stalls forever (`SyncLogicTest.cursorSkipsUnwatched`).
4. **A server answer is `rejected`.** That row counts as handled and the cursor passes it. It is shown in the status line, not retried forever (`SyncLogicTest.rejectedCountsAsHandled`).
5. **The user denies the SMS permission, or Android 13+ blocks it as restricted.** The checklist shows the App info button, not a crash or a silent empty sync (Task 4 manual check).

---

### Task 1: Repo, CI build and empty app

**Files:** `settings.gradle.kts`, `build.gradle.kts`, `app/build.gradle.kts`, `app/src/main/AndroidManifest.xml`, `.github/workflows/build.yml`, `.gitignore`, `README.md`, and a copy of the design spec and this plan in `docs/`.

- [ ] **Step 1:** `gh repo create Cecypo-Tech/sms-payments-bridge --private`, then clone it to `~/sms-payments-bridge`.
- [ ] **Step 2:** Make the signing key with openssl:
  - `openssl req -x509 -newkey rsa:2048 -keyout k.pem -out c.pem -days 10000 -nodes -subj "/CN=Cecypo SMS Payments Bridge"`
  - `openssl pkcs12 -export -inkey k.pem -in c.pem -name smsbridge -out ~/.android-keys/sms-payments-bridge.p12` (with a password)
  - Delete the `.pem` files.
  - `gh secret set SIGNING_KEYSTORE_B64 < <(base64 -w0 ~/.android-keys/sms-payments-bridge.p12)` and `gh secret set SIGNING_PASSWORD`.
  - Done when `gh secret list` shows both.
- [ ] **Step 3:** Create the project with the versions above.
  - Manifest permissions: `READ_SMS`, `RECEIVE_SMS`, `INTERNET`, `RECEIVE_BOOT_COMPLETED` and `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`.
  - `MainActivity` shows "SMS Payments Bridge".
  - The release `signingConfig` reads `storeFile` from env `SIGNING_KEYSTORE_PATH`, sets `storeType = "pkcs12"`, takes the store and key password from `SIGNING_PASSWORD`, and uses `keyAlias = "smsbridge"`. If the env var is missing, it falls back to unsigned, so a local or PR build still configures.
  - `build.yml` runs on push and workflow_dispatch: checkout → setup-java 17 → setup-gradle (8.11.1) → decode the secret into `$RUNNER_TEMP/ks.p12` → `gradle test assembleRelease` → `apksigner verify` → upload `app-release.apk` as an artifact named `sms-payments-bridge-<short sha>`.
- [ ] **Step 4:** Commit `chore: project skeleton and CI build` and push to `origin/main`. Pass when `gh run watch` ends green and `gh run download` yields the APK.

### Task 2: Pure sync logic and the API client

**Files:**
- Create: `app/src/main/java/tech/cecypo/smsbridge/SyncLogic.kt`, `Api.kt`, `Prefs.kt`
- Test: `app/src/test/java/tech/cecypo/smsbridge/SyncLogicTest.kt`, `ApiParseTest.kt`

**Interfaces (produced):**

```kotlin
data class Sms(val id: Long, val sender: String, val body: String, val dateMs: Long, val simSlot: Int?)
data class UploadResult(val phoneSmsId: Long, val status: String, val error: String?)

object SyncLogic {
    fun watched(rows: List<Sms>, senders: Set<String>): List<Sms>            // sender.uppercase() in senders
    fun nextCursor(scanned: List<Sms>, results: List<UploadResult>?, current: Long): Long
    // results == null means the upload failed -> current.
    // Otherwise -> max id of scanned (watched or not), because every uploaded row got a
    // result (accepted, duplicate or rejected).
    fun toUploadJson(deviceId: String, rows: List<Sms>): String               // the upload contract body
}

class Api(baseUrl: String, key: String, secret: String) {
    fun getConfig(deviceId: String, deviceName: String, appVersion: String): Config     // throws ApiException
    fun upload(deviceId: String, rows: List<Sms>): List<UploadResult>
    fun stats(deviceId: String): Stats
    companion object { fun parseConfig(json: String): Config; fun parseUpload(json: String): List<UploadResult>; fun parseStats(json: String): Stats }
}
data class Config(val enabled: Boolean, val device: String, val watchedSenders: Set<String>, val backfillDays: Int)
data class DayCount(val date: String, val matched: Int, val unmatched: Int, val ignored: Int, val duplicate: Int, val error: Int)
data class Event(val time: String, val sender: String, val status: String, val entry: String?, val amount: Double?)
data class Stats(val daily: List<DayCount>, val unmatchedTotal: Int, val lastPostedAt: String?, val events: List<Event>)
class ApiException(val httpCode: Int, message: String) : Exception(message)
```

- `Api` parses the Frappe `{"message": …}` wrapper. On a non-2xx response, it raises `ApiException` with the server's `_server_messages` or `exception` text, so a 403 "SMS device disabled" reaches the status line verbatim.
- `Prefs` keys: `url`, `apiKey`, `apiSecret`, `deviceId` (a UUID generated once), `deviceName`, `cursor` (Long, -1 = not initialised), `maxDate` (Long ms, -1 = unset; advanced with `cursor`), `senders` (StringSet), `lastSyncAt`, `lastError`, `autostartDone` (Boolean), `disclosureAccepted` (Boolean).

- [ ] **Step 1: Write failing tests:**
  - `cursorUnchangedOnFailure`: `nextCursor(rows 5..9, null, 4) == 4`.
  - `cursorSkipsUnwatched`: scanned ids 5..9, none watched, results empty list → 9.
  - `rejectedCountsAsHandled`: results include `rejected` → max id.
  - `watchedIsCaseInsensitive`: sender `Mpesa` with senders `{"MPESA"}` → kept.
  - `uploadJsonShape`: has keys `device_id` and `messages[0].phone_sms_id`, `sender`, `body`, `received_at_ms`, `sim_slot`.
  - `ApiParseTest.parsesStatsFixture`: a fixture JSON exactly as in the contract → `daily.size == 14` and `lastPostedAt` parsed.
  - `ApiParseTest.nullLastPostedAt`.
- [ ] **Step 2:** Push the tests only, and watch the CI run with `gh run watch`. Expect it to fail at `test` (unresolved references).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Commit `feat: sync logic and API client`, push, and `gh run watch`. Expect green.

### Task 3: Inbox reader, SyncWorker and triggers

**Files:**
- Create: `Inbox.kt`, `SyncWorker.kt`, `SmsReceiver.kt`, `BootReceiver.kt`, `Sync.kt`
- Modify: `AndroidManifest.xml`. Add the receivers: `SMS_RECEIVED` with priority 999, exported, permission `android.permission.BROADCAST_SMS`; and `BOOT_COMPLETED`.

**Interfaces:**
- `Inbox.readAfter(ctx, afterId: Long, maxDate: Long, limit: Int = 100): List<Sms>` queries `Telephony.Sms.Inbox.CONTENT_URI` for `_id > ?` (or `_id > ? OR date > ?` when `maxDate >= 0`), ordered by `_id ASC`, with the `LIMIT` in the sort order. `simSlot` comes from `sub_id`; if the provider rejects that column the query is retried without it and `simSlot` is null.
- `Inbox.cursorForBackfill(ctx, days: Int): Long`: the largest `_id` with `date < now - days`, or 0 if there is none.
- `Sync.request(ctx)`: a unique one-time work named `"sync"`, not expedited (no foreground service), `APPEND_OR_REPLACE`, network-connected constraint; `Sync.request(ctx, delaySeconds = 0)`, and `SmsReceiver` passes 15 s so the SMS app has written the row.
- `Sync.schedulePeriodic(ctx)`: unique periodic work `"sync-periodic"`, 15 minutes, `KEEP`.
- `SyncWorker.doWork()`:
  1. `getConfig`. Save the senders. If `enabled` is false, record that in `lastError` and return success.
  2. If the cursor is -1, set it to `cursorForBackfill(backfillDays)` and `maxDate` to the backfill cutoff.
  3. Loop (return `retry` if `isStopped`): `SyncLogic.fresh(readAfter(cursor, maxDate), cursor, maxDate)` (rows with `_id > cursor` or `date > maxDate`). Stop when empty. Upload the watched rows (skip the call if there are none). Set `cursor` and `maxDate` to `nextCursor(...)` and `nextMaxDate(...)`. `phone_sms_id` on the wire is `"<_id>-<date ms>"`. If the upload throws, save `lastError` and return `Result.retry()`.
  4. Save `lastSyncAt`, clear `lastError`, return success.
- Triggers: `SmsReceiver` and `BootReceiver` call `Sync.request`. `MainActivity.onResume` calls `Sync.request` and `Sync.schedulePeriodic`.

- [ ] **Step 1:** There is no new unit test; the logic is covered by Task 2. Commit `feat: inbox sync worker and triggers`, push, and `gh run watch`. Expect green.

### Task 4: Screens (setup, checklist, home)

**Files:**
- Create: `MainActivity.kt` (replace the stub), `BarChartView.kt`, `res/layout/{setup,checklist,home,event_row}.xml`, `res/values/strings.xml`

**Behaviour:**
- **Setup** fields: URL, API key, API secret, device name (default `Build.MANUFACTURER + " " + Build.MODEL`). **Test connection** runs `getConfig` off the main thread. On success it saves the fields and moves to Checklist; on an error it shows the message. A URL that isn't `https://` is refused before any network call.
- **Disclosure** (shown once, before the checklist; Play's prominent-disclosure rule, worded now so nothing changes later). Exact copy:
  > **SMS Payments Bridge reads your SMS.** It reads text messages from the bank and M-Pesa senders your company's ERPNext lists, and sends them to your company's ERPNext server at {url} to record payments. Messages from any other sender are never read into an upload or sent. You can stop it at any time by uninstalling the app.

  Buttons: **I agree** (sets `disclosureAccepted` and continues) and **Cancel** (back to Setup). The SMS permission button is disabled until the user agrees.
- **Checklist rows**, each with a tick and an action button:
  1. **SMS permission.** The button requests `READ_SMS` and `RECEIVE_SMS`. If the request is refused permanently, or on Android 13+ it isn't granted after the prompt, the button changes to "Open App info". Its explanation reads: "Tap ⋮ → Allow restricted settings, then come back."
  2. **Battery optimisation.** `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`. The tick reads `PowerManager.isIgnoringBatteryOptimizations`.
  3. **Autostart.** The button tries known manufacturer intents in order, each guarded by `resolveActivity`:
     - Xiaomi: `com.miui.securitycenter/com.miui.permcenter.autostart.AutoStartManagementActivity`
     - Tecno/Infinix: `com.transsion.phonemaster/com.cyin.himgr.autostart.AutoStartActivity`
     - Samsung: `com.samsung.android.lool/com.samsung.android.sm.ui.battery.BatteryActivity`
     - otherwise App info.

     There's a manual "Done" checkbox that sets `autostartDone`.
  - **Continue** is enabled once 1 and 2 are ticked.
- **Home:**
  - Status line: "Last sync HH:MM" or `lastError` in red.
  - Unmatched count (large), and "Last posted: …" (`lastPostedAt` or "—").
  - `BarChartView`: 14 bars stacked by matched, unmatched and other. It is drawn with `Canvas`, has day labels for every other bar, and supports dark mode via theme attributes.
  - Event list (`RecyclerView` is not in the dependency list, so use a `LinearLayout` with up to 50 inflated `event_row` views).
  - Pull to refresh calls `Sync.request`, then `stats`.
  - Menu item **Edit connection** goes back to Setup, keeping the cursor.
- **Routing:** `MainActivity` shows Setup if `url` is empty, Disclosure if `disclosureAccepted` is false, Checklist if row 1 or 2 isn't ticked, and Home otherwise.

- [ ] **Step 1:** Commit `feat: setup, checklist and home screens`, push, and `gh run watch`. Expect green.
- [ ] **Step 2:** Download the APK from the run (`gh run download`) and send it to the user's phone (SendUserFile, or `adb install` if a phone is attached). The user walks the three screens and reports back. Fix anything they hit before Task 5.
- [ ] **Step 3:** Commit any fixes, push, and the run is green.

### Task 4b: Sample Picker (user decision 2026-11-10)

**Goal:** let the user hand-pick SMS from the phone's inbox, from any sender, and send them to ERPNext as samples for building rules. Nothing is sent without an explicit tick.

**Files:**
- Create: `SamplePickerActivity.kt` (or a fourth view in MainActivity, whichever matches Task 4's structure), `res/layout/sample_picker.xml`, `res/layout/sample_row.xml`
- Modify: `Inbox.kt` (a `recent(ctx, limit)` read: newest first, any sender), the Home menu, `strings.xml` (the disclosure copy), and `SyncLogic.kt` only if a pure helper is needed

**Behaviour:**
- **Opening it.** A Home menu item, **Send samples**, opens the picker. It's only reachable once Setup has passed and the SMS permission is granted. Otherwise it shows the reason and does nothing.
- **List.**
  - The most recent 200 inbox SMS, newest first.
  - Each row shows a checkbox, the sender, the date and time, and the first 2 lines of the body (ellipsized).
  - A sender filter at the top: a text field, case-insensitive substring on the sender.
  - Rows from senders already in `watched_senders` (Prefs `senders`) get a small "watched" tag. They can still be picked.
  - Use a `ScrollView` + `LinearLayout`; RecyclerView isn't in the dependency list. Inflating 200 rows is acceptable.
- **Sending.**
  - The **Send N samples** button is disabled when nothing is ticked.
  - On tap it shows a confirm dialog: "Send N messages to {url}?"
  - On confirm it uploads the picked rows through the existing `Api.upload`, off the main thread. It uses the same `Sms` objects and the same `"<_id>-<date ms>"` key, so a sample that is later forwarded normally comes back `duplicate`, never twice.
  - Batches of up to 100 (reuse the existing batching or chunk).
  - **Never touch `cursor` or `maxDate`.** Samples are outside the sync cursor.
- **Result.**
  - A toast or dialog summarising accepted / duplicate / rejected counts.
  - On an exception, show the error text from `Api` (no stack traces, no credentials).
  - Ticks are cleared after a successful send.
- **Disclosure copy change** (replace the Task 4 text exactly):
  > **SMS Payments Bridge reads your SMS.** It reads text messages from the bank and M-Pesa senders your company's ERPNext lists, and sends them to your company's ERPNext server at {url} to record payments. Messages from any other sender are never sent, unless you choose them yourself in Send samples. You can stop it at any time by uninstalling the app.
- **Server:** no change. `upload` already accepts any sender, and samples land in the SMS Log (Unmatched until a rule fits, then the normal pipeline).

**Tests:** a pure unit test for any helper you add, e.g. filter matching or chunking. The UI is checked on the phone by the user, through the controller.

- [ ] **Step 1:** Commit `feat: sample picker`, push, CI green.
- [ ] **Step 2 (controller + user):** Send the APK. The user picks 3–5 real M-Pesa and bank SMS. The controller confirms they land in the SMS Log on dev.localhost.

### Task 5: README

- [ ] **Step 1:** Write `README.md`. Cover:
  - downloading the APK from the latest green run;
  - installing it from unknown sources;
  - the disclosure and checklist;
  - creating the ERPNext API user with only the `SMS Gateway` role;
  - a "Later: Google Play" section listing spec §8's two steps (developer verification for the package and certificate under the Cecypo organisation account, then an optional listing with the SMS permission declaration). It names the files a listing will need: a privacy policy URL and a demo video of the disclosure and permission flow.
- [ ] **Step 2:** Commit `docs: README`, push, and the CI run is green.

### Task 6: Real-phone acceptance (with the user)

Prerequisites: the Frappe side is through Task 5 on `dev.localhost` (reachable as `https://erp.example.com`), with an M-Pesa rule using the sample pattern, and the worker running.

- [ ] **Step 1:** Install the APK on a phone (`adb install` over USB or Wi-Fi, or copy the file over). Complete Setup against `https://erp.example.com` and work through the checklist.
- [ ] **Step 2:** Use the user's own phone. Wait for, or trigger, a real watched-sender SMS (for example a small M-Pesa transfer). Alternatively, send from a second phone whose number is added to `sms_extra_senders`. Within a minute:
  - an SMS Log appears in ERPNext;
  - the Home event list shows it;
  - today's bar goes up.
- [ ] **Step 3:** Airplane mode on, receive two SMS, airplane mode off. Both arrive once (spec acceptance 7).
- [ ] **Step 4:** An SMS from an unwatched sender never appears in SMS Log (acceptance 6).
- [ ] **Step 5:** Disable the SMS Device in ERPNext. The phone's status line shows "SMS device disabled".
- [ ] **Step 6:** Record the results in `docs/acceptance.md`, commit and push. Then use superpowers:requesting-code-review on the repo.

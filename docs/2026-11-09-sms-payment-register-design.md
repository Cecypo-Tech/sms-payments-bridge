## SMS Payment Register — Design

### 1. Intent

Every Kenyan bank and M-Pesa sends an SMS for each transaction. Today an accountant reads
that SMS, types a Payment Entry by hand, and reconciles against the bank statement the next
morning. This project turns those SMS into ERPNext records automatically: an "integration
without an integration" that works with any bank that sends SMS.

Two parts:

1. **An Android app** on the office phone (usually one, sometimes two) that forwards SMS
   from watched senders to ERPNext. It is deliberately dumb: no rules or settings on the
   phone beyond the connection itself.
2. **A new `SMS Payments` module in `cecypo_bank_integrations`** that holds all the logic:
   rules, the register, party matching and Payment Entry creation, built the way the QZ
   app's print routing rules are (Python expressions, priorities, desk UI).

Example SMS the system must handle:

> Confirmed. KES. 29,000.00 from JANE WANJIKU MWANGI received via M-Pesa Ref. UKA1B2C3D4 on 09-11-2026 at 09:47. Thank you.

### 2. Goals, non-goals, anti-goals

**Goals (user)**
- The phone app stores an ERPNext URL, API key and secret. That is its only configuration.
- The phone reads SMS and forwards those from the senders ERPNext tells it to watch.
- The phone shows: a chart of daily messages, how many messages matched no rule, and the
  date-time of the last posted entry, plus an event log.
- All settings and rules live in ERPNext.
- Every matched SMS creates an **SMS Payment Register** entry first, recording where and
  how it was created. Creating the Payment Entry immediately is an optional setting.
- A rule decides the payment type: **Receive**, **Pay** or **Internal Transfer**. Outgoing
  payments are recorded as supplier payments.
- From a register entry, the user can create a **party rule**: "JANE WANJIKU MWANGI →
  Customer Acme Holdings Ltd". All of that payer's future payments go to that customer
  (or supplier) automatically.
- Building a rule starts from a real SMS. (This replaces the original "paste an SMS into the
  phone app" idea, now that settings moved to ERPNext.)

**Non-goals**
- No changes to DTB IPN, I&M, KCB M-Pesa or `Mpesa C2B Payment Register`. Rules apply
  only to SMS. SMS payments do not appear in the POS or in C2B auto-matching; that can be
  added later.
- No Google Play listing (see constraints).
- No allocation to invoices. The Payment Entry is unallocated, and reconciliation stays
  with ERPNext's Payment Reconciliation tool, as today.
- No fuzzy or automatic name-to-customer guessing. Parties come only from party rules or
  from the accountant.
- Single currency per rule (company currency). No multi-currency.

**Anti-goals (failure even if it "works")**
- One real transaction creating two register entries or two Payment Entries. This covers
  two phones, resent batches and reprocessing.
- A money SMS silently disappearing. Every SMS from a watched sender is logged, and the ones
  that match no rule are counted and visible.
- The phone forwarding personal messages from senders nobody asked to watch.
- The phone app needing more setup than URL, key and secret.

### 3. Constraints

- **Google Play policy:** apps that read SMS must be the default SMS handler. The app is
  distributed as a signed APK and installed directly (sideloaded) on the office phone.
- **Background limits:** Android kills or delays background work, so the design cannot
  depend only on the SMS-received broadcast (see §5).
- **Toolchain:** this machine has no JDK, Gradle or Android SDK. The builder installs
  JDK 17 and the Android command-line tools in WSL, or builds the APK in CI.
- **Bench:** processing runs in background jobs, so the `short` worker must be running on
  this bench (see the bench CLAUDE.md). Tests run against `dev.localhost`.
- Lands on `cecypo_bank_integrations` → `upstream/version-16`, following the existing
  per-bank module layout (`dtb/`, `kcb_mpesa/`, `im_bank/`).

### 4. ERPNext side (`cecypo_bank_integrations/sms_payments/`)

New Module Def `SMS Payments`, surfaced in the existing `Bank Integrations` workspace. New
role **SMS Gateway**, given to the API user the phone logs in as. It may call the phone
endpoints and nothing else.

#### 4.1 DocTypes

**SMS Device**: one per phone, like QZ `Print Station`.
- `device_id` (stable ID the app generates on install), `device_name`, `enabled`,
  `app_version`, `last_seen`, `last_error`.
- Auto-created on the phone's first call *(my call)*. Disabling it makes ERPNext reject
  that phone's uploads.

**SMS Log**: every SMS the phone forwards, stored as received.
- `device`, `sender`, `body` (Long Text), `received_at` (the phone's timestamp),
  `phone_sms_id`, `sim_slot`.
- `status`: `Unmatched` / `Matched` / `Ignored` / `Duplicate` / `Error`.
- `sms_rule`, `register_entry` (link), `error` (text).
- Idempotency key: (device, phone_sms_id). A batch the phone resends is accepted and does
  nothing.
- Buttons: **Create Rule** (§4.3) and **Reprocess**. List-view action: **Reprocess
  Unmatched**, so SMS that arrived before their rule existed can still be picked up.

**SMS Rule**: decides what an SMS means.
- `rule_name`, `enabled`, `priority` (highest wins; first match stops).
- `senders`: one sender ID per line (e.g. `MPESA`, `DTB-KENYA`), exact, case-insensitive.
- `pattern`: a Python regex with named groups. Recognised groups: `amount` (required unless
  the action is Ignore), `reference` (required unless Ignore), `party_name`, `party_phone`,
  `date`, `time`, `charges`. Others are kept but ignored.
- `charges_account` and `charges_cost_center` (optional). When the rule sets a charges
  account and the SMS yields a non-zero `charges` group (e.g. "Transaction cost,
  Ksh33.00"), the fee is posted on the Payment Entry as a deduction row against that
  account, so the bank or M-Pesa account moves by exactly what the statement shows. On a
  Pay, the account drops by amount + charges. On a Receive, it gains amount − charges.
  With no charges account set, the fee is only recorded on the register entry. *(User:
  optional fee posting. My call: the deduction-row mechanics.)*
- `condition_eval` (optional): a Python expression run with `frappe.safe_eval`, the same way
  as `cecypo_qz_extension/api/queue.py`. Context: `sms` (sender, body, received_at) and
  `m` (dict of extracted groups). Example: `"received" in sms.body.lower()`.
- `date_format` (e.g. `%d-%m-%Y`); a missing date or time falls back to `received_at`.
- `action`: **Create Entry** or **Ignore**. Ignore is for balance alerts, Fuliza notices
  and promos, so they are logged as `Ignored` and not counted as unmatched.
- `payment_type`: **Receive** / **Pay** / **Internal Transfer**.
- `company`, `mode_of_payment`, `paid_to` (Receive and Internal Transfer), `paid_from`
  (Pay and Internal Transfer).
- `auto_post`: when checked, an entry that has a party (or is an Internal Transfer) is
  submitted immediately, which creates and submits the Payment Entry.
- Validation: the pattern compiles, `amount` and `reference` groups exist, and accounts
  belong to `company`.
- **Test panel**: a button that runs the rule against the latest 20 SMS Log entries from
  its senders and shows which matched and what each one extracted. Nothing is saved.

**SMS Payment Register**: submittable, named `SMSPAY-.YYYY.-.#####`.
- Origin: `sms_log`, `sms_rule`, `device`, `sender`, `raw_message`.
- Extracted: `reference`, `amount`, `charges`, `posting_date`, `posting_time`,
  `party_name_in_sms`, `party_phone`.
- Posting: `payment_type`, `company`, `mode_of_payment`, `paid_from`, `paid_to`,
  `party_type` (Customer for Receive, Supplier for Pay, empty for Internal Transfer),
  `party`, `sms_party_rule` (which rule set the party), `payment_entry`.
- **Unique (company, reference)**. The second phone's copy of the same SMS, or a reprocess,
  produces an SMS Log with status `Duplicate` and no new entry.
- `on_submit`: requires a party for Receive and Pay, then creates the Payment Entry and
  submits it, with `reference_no = reference` and `reference_date = posting_date`.
  `on_cancel`: cancels the linked Payment Entry, as `Mpesa C2B Payment Register` already
  does.
- Button **Create Party Rule** (on a draft with no party): opens a dialog pre-filled with
  the SMS name and phone, and asks for the party.

**SMS Party Rule**: maps a payer or payee name to a party.
- `match_on`: `Name` or `Phone`. `match_type`: `Exact` / `Contains` / `Regex`. `value`.
- `party_type` (Customer / Supplier), `party`, `enabled`, `priority`.
- Matching normalises names (uppercase, collapsed spaces). Phone rules are tried before
  name rules, and Exact before Contains before Regex, then by priority.
- After a party rule is saved, it is applied to existing **draft** register entries it
  matches, and those entries are auto-posted if their SMS Rule says so *(my call)*.
- Only rules whose `party_type` fits the entry's payment type are considered (Customer for
  Receive, Supplier for Pay).

**Settings**: a new **SMS** tab on the existing `Bank Integration Settings` single.
- `sms_enabled` (master switch; when off, the phone endpoints refuse with a clear message).
- `extra_senders` (watched even with no rule yet, so unmatched SMS from a new bank get
  logged).
- `backfill_days` (default 3): how far back a newly set-up phone uploads.

#### 4.2 Phone endpoints (`sms_payments/api.py`, whitelisted)

Authentication: `Authorization: token <key>:<secret>` of a user with the SMS Gateway role.
Every call sends `device_id`.

- `get_config(device_id, device_name, app_version)` → `{watched_senders, backfill_days,
  enabled}`. It registers the device or updates it and sets `last_seen`. Watched senders
  are the union of enabled rules' `senders` and `extra_senders`.
- `upload(device_id, messages: [{phone_sms_id, sender, body, received_at, sim_slot}])` →
  per-message `accepted` / `duplicate`. The upload only writes SMS Log rows. Rule
  processing is enqueued to the `short` queue so a slow Payment Entry never blocks the
  phone. Batches are capped at 100 messages.
- `stats(device_id)` → daily counts for the last 14 days (matched / unmatched / ignored /
  duplicate), the current unmatched total, the last posted register entry's date-time,
  and the 50 most recent SMS Log events (time, sender, status, register entry name,
  amount).

#### 4.3 Processing pipeline (background job per SMS Log)

1. Find enabled rules whose `senders` include the log's sender, sorted by priority. Run the
   pattern; if `condition_eval` is set, it must also be true. The first hit wins.
2. No hit → `Unmatched`. Ignore action → `Ignored`.
3. Parse `amount` (strip commas and currency text) and the date and time. A failure →
   `Error` with the message.
4. Duplicate checks:
   - If (company, reference) already exists in the register with the **same amount and
     payment type**, the log is `Duplicate`, linked to the existing entry.
   - Same reference with a different amount or type (a reversal, a correction) → `Error`
     ("reference already used by SMSPAY-…"). This stays visible and counted, so the
     accountant handles it; it is never silently swallowed. *(My call.)*
   - If a **submitted Payment Entry** in the company already has `reference_no` equal to the
     reference, the log is `Duplicate` and linked to that Payment Entry. This stops a
     double post when the same account is also fed by DTB IPN, KCB IPN or the C2B
     register, without touching those integrations. *(My call.)*
5. Insert the SMS Payment Register entry and apply party rules. If `auto_post` is on and the
   entry is postable, submit it. A Payment Entry failure leaves the entry as a draft, puts
   the error on the SMS Log, and does not roll back the register entry.
6. Set the log to `Matched` with links.

**Create Rule from an SMS Log**: opens a new SMS Rule with the sender filled in and a
suggested pattern. The SMS text is escaped, and recognisable pieces are replaced with named
groups: an amount like `29,000.00`, a reference (10 uppercase letters and digits, or a word
after `Ref`), a date, a time, and the uppercase words after `from` or `to` as `party_name`.
The user edits the result and checks it with the Test panel. The suggestion is a starting
point, not a guarantee.

**Internal transfers usually produce two SMS** (a debit from one account and a credit into
the other, with different references). Only one side posts: one side's rule is Internal
Transfer and the other side's rule is **Ignore**. The SMS Rule form says this in its help
text. Pairing the two SMS automatically is out of scope. *(My call.)*

Example rule for the sample SMS:
```
senders:  <the shortcode it came from>
pattern:  Confirmed\. KES\. (?P<amount>[\d,]+\.\d{2}) from (?P<party_name>.+?) received via M-Pesa Ref\. (?P<reference>\w+) on (?P<date>\d{2}-\d{2}-\d{4}) at (?P<time>\d{2}:\d{2})
date_format: %d-%m-%Y
payment_type: Receive
```

### 5. Android app

**Name: SMS Payments Bridge** *(user)*. The code lives in a new private repo,
`Cecypo-Tech/sms-payments-bridge` *(user approved creating it; my call that the repo name
follows the app name)*.

Native Kotlin, a single activity, as few libraries as possible *(my call)*. No local
database. It ships as a signed APK.

**Screens**
- **Setup**: ERPNext URL (HTTPS required), API key, API secret, device name (defaults to
  the phone model). **Test connection** calls `get_config`. The app then asks for the SMS
  permission and for an exemption from battery optimisation.
- **Home**:
  - a bar chart of daily messages for 14 days (drawn on a Canvas, no chart library);
  - an "unmatched" count;
  - "last posted entry" date-time;
  - the event log list from `stats`;
  - a status line: last sync time, and the last error if any.
  - Pull to refresh. A menu has **Edit connection**.

**Forwarding: the phone's SMS inbox is the queue *(my call)*.**
- The app keeps one value: the `_id` of the last forwarded inbox row.
- A sync reads `content://sms/inbox` for rows after that `_id` from watched senders,
  uploads them in batches, and moves the cursor forward only after ERPNext accepts them.
- On first setup, the cursor starts `backfill_days` back.
- Syncs are triggered by the SMS-received broadcast (expedited WorkManager job), by
  WorkManager every 15 minutes, by boot, and by opening the app.
- If the phone was off or the app was killed, the next sync catches up. Server-side
  idempotency makes retries safe, and multi-part SMS arrive already joined in the inbox.
- Watched senders are refreshed from `get_config` on each sync. SMS from other senders are
  never read into an upload.
- Credentials live in app-private storage, with Android backup disabled for the app.

**Permissions:** `READ_SMS`, `RECEIVE_SMS`, `INTERNET`, `RECEIVE_BOOT_COMPLETED`, and
`REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`.

**Sideload reality *(my call)*:** on Android 13 and later, a sideloaded app can't be granted
SMS permission until "Allow restricted settings" is switched on in its App info screen. Many
phone makers (Tecno, Infinix, Xiaomi, Samsung) also need a manual "autostart" or "no
restrictions" setting. Setup therefore ends with a short checklist screen. Each step has a
button that opens the right settings page where Android allows it, and a tick once the app
can confirm the step (permission granted, battery exemption on). The app supports Android 15
(API 35) and later (changed 2026-11-15; it first supported Android 8). Cecypo staff install it, so the checklist is written for them.

### 6. Acceptance criteria

1. The sample SMS, with a matching rule, becomes a register entry with amount 29,000.00,
   reference `UKA1B2C3D4`, payer `JANE WANJIKU MWANGI`, and posting 2026-11-09 09:47,
   linked to its SMS Log.
2. **Create Party Rule** on that entry → Customer X. The entry and all future SMS from that
   name get Customer X. With `auto_post`, a submitted Payment Entry (Receive, reference
   `UKA1B2C3D4`) exists and links both ways.
3. The same SMS uploaded by a second device, or uploaded twice, leaves exactly one register
   entry and one Payment Entry. The extra copy is an SMS Log with status `Duplicate`.
4. An outgoing-payment SMS with a Pay rule and a supplier party rule → a Pay Payment Entry
   to that supplier. A transfer SMS with an Internal Transfer rule → an Internal Transfer
   between the rule's two accounts.
5. An SMS from a watched sender that matches no rule appears as `Unmatched`, raises the
   phone's unmatched count, and after a rule is created, **Reprocess Unmatched** turns it
   into an entry.
6. SMS from senders not being watched never reach ERPNext.
7. With the phone offline for a day and then reconnected, every missed SMS arrives once.
8. Cancelling a register entry cancels its Payment Entry.
9. A Pay SMS that includes "Transaction cost, Ksh33.00", on a rule with a charges account,
   gives a Payment Entry whose effect on the paying account is amount + 33.00, with the
   33.00 in the charges account.
10. The same reference with a different amount → SMS Log `Error`, not `Duplicate`. A
    reference already on a submitted Payment Entry from another integration → `Duplicate`,
    with no second post.

### 7. Left to the builder

- Exact field labels, layout and naming series beyond what is stated.
- Test structure (Frappe tests for the pipeline, dedupe, party rules and Payment Entry; a
  JVM unit test for the inbox-cursor filter).
- Package ID and signing-key handling (the signing keystore never goes into the repo).

### 8. Delivery order and distribution (revised 2026-11-10)

1. **The ERPNext module comes first.** It also adds **Add SMS manually** on the SMS Log list, for pasting real SMS from a phone, or SMS a customer sends over WhatsApp. These become test data and starting points for rules (the user's original "paste an SMS" idea, now in ERPNext). The user's own SMS prove the rules before any app exists.
2. **Then the SMS Payments Bridge app**, built in GitHub Actions only.
3. **Distribution, for now:** a signed APK installed directly ("unknown sources"). The user decided this.
4. **Later, under Cecypo's existing Google Play organisation account** (not in the current plans):
   - **Developer verification for sideloaded apps** (worldwide from 2027): register the package name and signing certificate in the Play/Android Developer Console.
   - **Optionally, a Play listing.** It needs the SMS permission exception (Permissions Declaration Form, claiming "Enterprise archive / enterprise device management"), a privacy policy and a store listing. Google decides case by case.
   - The app is built now so it won't need rework for either: a stable package ID, a stable signing key (also usable as the Play upload key), targetSdk 36, a prominent disclosure screen before the SMS permission request, and forwarding of watched financial senders only.
5. **iOS is out of scope.** iOS gives apps no SMS access.

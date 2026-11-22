import hashlib
from datetime import UTC, datetime, timezone

import frappe
from frappe.utils import add_days, convert_utc_to_system_timezone, get_datetime, now_datetime, today

from sms_payments.sms_payments.pipeline import enqueue_log

SETTINGS = "SMS Payments Settings"
MAX_BATCH = 100
MAX_BODY = 2000
DAILY_STATUSES = ("Matched", "Unmatched", "Ignored", "Duplicate", "Error")


def _check_caller():
	roles = frappe.get_roles()
	if "SMS Gateway" not in roles and "System Manager" not in roles:
		frappe.throw("Not permitted", frappe.PermissionError)


def _enabled():
	return bool(frappe.db.get_single_value(SETTINGS, "sms_enabled"))


def _watched_senders():
	lines = list(frappe.db.get_all("SMS Rule", {"enabled": 1}, pluck="senders"))
	lines.append(frappe.db.get_single_value(SETTINGS, "sms_extra_senders"))
	return sorted({s.strip().upper() for text in lines for s in (text or "").splitlines() if s.strip()})


def _device(device_id):
	"""Enabled device or PermissionError; touches last_seen."""
	if not device_id or not frappe.db.get_value("SMS Device", device_id, "enabled"):
		frappe.throw("SMS device disabled", frappe.PermissionError)
	frappe.local.flags.commit = True  # GET requests are rolled back otherwise
	frappe.db.set_value("SMS Device", device_id, "last_seen", now_datetime(), update_modified=False)


@frappe.whitelist()
def get_config(device_id, device_name=None, app_version=None):
	_check_caller()
	if not device_id:
		frappe.throw("device_id is required", frappe.ValidationError)
	frappe.local.flags.commit = True  # GET requests are rolled back otherwise
	values = {"last_seen": now_datetime()}
	if device_name:
		values["device_name"] = device_name
	if app_version:
		values["app_version"] = app_version
	if frappe.db.exists("SMS Device", device_id):
		frappe.db.set_value("SMS Device", device_id, values, update_modified=False)
	else:
		frappe.get_doc({"doctype": "SMS Device", "device_id": device_id, "enabled": 1, **values}).insert(
			ignore_permissions=True
		)
	enabled = _enabled() and bool(frappe.db.get_value("SMS Device", device_id, "enabled"))
	return {
		"enabled": enabled,
		"device": device_id,
		"watched_senders": _watched_senders() if enabled else [],
		"backfill_days": frappe.db.get_single_value(SETTINGS, "sms_backfill_days") or 0,
	}


def ingest(device, phone_sms_id, sender, body, received_at, sim_slot=None, is_sample=0):
	"""Insert a Pending SMS Log and queue it. Returns "accepted" or "duplicate"."""
	phone_sms_id = str(phone_sms_id)
	if frappe.db.exists("SMS Log", {"device": device or ("is", "not set"), "phone_sms_id": phone_sms_id}):
		return "duplicate"
	# savepoint so a failed insert (concurrent duplicate, validation) doesn't poison the batch
	frappe.db.savepoint("sms_ingest")
	try:
		log = frappe.get_doc({
			"doctype": "SMS Log", "device": device, "phone_sms_id": phone_sms_id, "sender": sender,
			"body": body, "received_at": received_at, "sim_slot": sim_slot, "status": "Pending",
			"is_sample": is_sample,
		})
		log.insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		frappe.db.rollback(save_point="sms_ingest")
		return "duplicate"
	except Exception:
		frappe.db.rollback(save_point="sms_ingest")
		raise
	enqueue_log(log.name)
	return "accepted"


@frappe.whitelist(methods=["POST"])
def upload(device_id, messages, sample=None):
	"""`sample`: the batch was picked by hand in Send samples; it is logged but never auto-posted."""
	_check_caller()
	_device(device_id)
	if not _enabled():
		frappe.throw("SMS Payments is disabled", frappe.ValidationError)
	if isinstance(messages, str):
		messages = frappe.parse_json(messages)
	messages = messages or []
	is_sample = frappe.utils.cint(frappe.utils.sbool(sample))
	if len(messages) > MAX_BATCH:
		frappe.throw(f"Too many messages (max {MAX_BATCH})", frappe.ValidationError)

	limits = {f: frappe.get_meta("SMS Log").get_field(f).length or 140 for f in ("phone_sms_id", "sender")}
	results = []
	for m in messages:
		out = {"phone_sms_id": "", "status": "rejected", "error": None}
		results.append(out)
		if not isinstance(m, dict):
			out["error"] = "message must be an object"
			continue
		sid = m.get("phone_sms_id")
		sid = "" if sid is None else str(sid)
		out["phone_sms_id"] = sid
		if not sid or not m.get("sender") or not m.get("body"):
			out["error"] = "phone_sms_id, sender and body are required"
			continue
		if len(sid) > limits["phone_sms_id"] or len(str(m["sender"])) > limits["sender"]:
			out["error"] = "phone_sms_id or sender too long"
			continue
		try:
			utc = datetime.fromtimestamp(int(m["received_at_ms"]) / 1000, UTC)
			received_at = convert_utc_to_system_timezone(utc).replace(tzinfo=None)
		except (KeyError, TypeError, ValueError, OverflowError, OSError):
			out["error"] = "received_at_ms is invalid"
			continue
		if len(str(m["body"])) > MAX_BODY:
			out["error"] = f"body too long (max {MAX_BODY})"
			continue
		try:
			sim = int(m["sim_slot"]) if m.get("sim_slot") is not None else None
		except (TypeError, ValueError):
			sim = None
		if sim is not None and not 0 <= sim <= 9:
			sim = None
		try:
			out["status"] = ingest(device_id, sid, str(m["sender"]), str(m["body"]), received_at, sim, is_sample)
		except (frappe.ValidationError, frappe.DataError) as e:
			out["status"], out["error"] = "rejected", str(e)[:200]
		# anything else (lock wait, deadlock) propagates: the request fails and the phone resends
	return {"results": results}


@frappe.whitelist()
def stats(device_id):
	_check_caller()
	_device(device_id)
	start = add_days(today(), -13)
	rows = frappe.db.sql(
		"""select date(received_at) d, status, count(*) c from `tabSMS Log`
		where device = %s and date(received_at) >= %s group by d, status""",
		(device_id, start),
	)
	by_day = {}
	for d, status, c in rows:
		by_day.setdefault(str(d), {})[status] = c
	daily = []
	for i in range(14):
		day = add_days(start, i)
		counts = by_day.get(day, {})
		daily.append({"date": day, **{s.lower(): counts.get(s, 0) for s in DAILY_STATUSES}})

	posted = frappe.db.sql(
		"""select posting_date, posting_time from `tabSMS Payment Register`
		where device = %s and docstatus = 1 order by posting_date desc, posting_time desc limit 1""",
		device_id,
	)
	last_posted = f"{posted[0][0]} {str(posted[0][1]).split('.')[0].rjust(8, '0')}" if posted else None

	events = frappe.db.sql(
		"""select l.received_at, l.sender, l.status, l.register_entry, r.amount
		from `tabSMS Log` l left join `tabSMS Payment Register` r on r.name = l.register_entry
		where l.device = %s order by l.received_at desc, l.creation desc limit 50""",
		device_id,
	)
	return {
		"daily": daily,
		"unmatched_total": frappe.db.count("SMS Log", {"device": device_id, "status": "Unmatched"}),
		"last_posted_at": last_posted,
		"events": [
			{"time": get_datetime(t).strftime("%Y-%m-%d %H:%M:%S"), "sender": s, "status": st,
				"entry": e, "amount": float(a) if a is not None else None}
			for t, s, st, e, a in events
		],
	}


@frappe.whitelist(methods=["POST"])
def add_manual_sms(sender, body, received_at):
	"""Enter an SMS by hand (old SMS, or one pasted from WhatsApp). Returns the log name."""
	frappe.only_for(("System Manager", "Accounts Manager"))
	sid = "man-" + hashlib.sha1(f"{sender}|{received_at}|{body}".encode()).hexdigest()[:16]
	ingest(None, sid, sender, body, received_at)
	return frappe.db.get_value("SMS Log", {"device": ("is", "not set"), "phone_sms_id": sid})

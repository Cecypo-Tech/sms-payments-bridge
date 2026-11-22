import hashlib

import frappe
from frappe.utils.synchronization import filelock

from sms_payments.sms_payments.parser import SMSParseError, find_rule
from sms_payments.sms_payments.party import find_party

PROCESSABLE = ("Pending", "Unmatched", "Error")


def enqueue_log(name):
	frappe.enqueue(
		"sms_payments.sms_payments.pipeline.process_log",
		queue="short",
		log_name=name,
		enqueue_after_commit=True,
		now=frappe.flags.in_test,
	)


@frappe.whitelist(methods=["POST"])
def reprocess(log_names=None):
	"""Queue Pending/Unmatched/Error logs again (all of them when no names given); returns the count."""
	frappe.only_for(("System Manager", "Accounts Manager"))
	if isinstance(log_names, str):
		log_names = frappe.parse_json(log_names)
	filters = {"status": ("in", PROCESSABLE)}
	if log_names:
		filters["name"] = ("in", log_names)
	names = frappe.get_all("SMS Log", filters=filters, pluck="name")
	for n in names:
		enqueue_log(n)
	return len(names)


def process_log(log_name):
	# The job inherits the enqueuing user, e.g. the phone's SMS Gateway user, which can't read accounts.
	# Rules are admin-configured, so the system posts what they describe.
	caller = frappe.session.user
	frappe.set_user("Administrator")
	try:
		log = frappe.get_doc("SMS Log", log_name)
		if log.status not in PROCESSABLE:
			return
		_process(log)
	finally:
		frappe.set_user(caller)
	# ponytail: commit only here; the job runs outside a request, tests roll back instead
	if not frappe.flags.in_test:
		frappe.db.commit()


def _set(log, status, **kw):
	log.db_set({"status": status, "sms_rule": None, "register_entry": None, "payment_entry": None,
		"error": None, **kw})


def _process(log):
	try:
		found = find_rule(log.sender, log.body, log.received_at)
	except SMSParseError as e:
		return _set(log, "Error", error=str(e))
	if not found:
		return _set(log, "Unmatched")
	rule, values = found
	if values.get("action") == "Ignore":
		return _set(log, "Ignored", sms_rule=rule.name)

	ref = values["reference"]
	key = hashlib.sha1(f"{rule.company}:{ref}".encode()).hexdigest()
	# ponytail: filelock is per-host (sites/<site>/locks); multi-host workers would need a DB-level
	# unique key or GET_LOCK. Commits inside the lock start a fresh snapshot and publish the insert
	# before release (REPEATABLE-READ would otherwise hide it from the next worker).
	with filelock(f"sms-ref-{key}"):
		if not frappe.flags.in_test:
			frappe.db.commit()
		# another worker may have processed this log while we waited for the lock
		if frappe.db.get_value("SMS Log", log.name, "status") not in PROCESSABLE:
			return
		existing = frappe.db.get_value(
			"SMS Payment Register",
			{"company": rule.company, "reference": ref, "docstatus": ("!=", 2)},
			["name", "amount", "payment_type"],
			as_dict=True,
		)
		if existing:
			if abs(existing.amount - values["amount"]) < 0.005 and existing.payment_type == rule.payment_type:
				return _set(log, "Duplicate", sms_rule=rule.name, register_entry=existing.name)
			return _set(
				log, "Error", sms_rule=rule.name,
				error=f"Reference {ref} already used by {existing.name} with a different amount or type",
			)
		pe = frappe.db.get_value(
			"Payment Entry", {"company": rule.company, "reference_no": ref, "docstatus": 1}
		)
		if pe:
			return _set(log, "Duplicate", sms_rule=rule.name, payment_entry=pe)

		frappe.db.savepoint("sms_insert")
		try:
			party = find_party(rule.payment_type, values["party_name"], values["party_phone"])
			entry = frappe.get_doc({
				"doctype": "SMS Payment Register",
				"payment_type": rule.payment_type,
				"company": rule.company,
				"mode_of_payment": rule.mode_of_payment,
				"paid_from": rule.paid_from,
				"paid_to": rule.paid_to,
				"charges_account": rule.charges_account,
				"charges_cost_center": rule.charges_cost_center,
				"sms_rule": rule.name,
				"reference": ref,
				"amount": values["amount"],
				"charges": values["charges"],
				"posting_date": values["posting_date"],
				"posting_time": values["posting_time"],
				"party_name_in_sms": values["party_name"],
				"party_phone": values["party_phone"],
				"sms_log": log.name,
				"device": log.device,
				"sender": log.sender,
				"raw_message": log.body,
				**({"party_type": party[0], "party": party[1], "sms_party_rule": party[2]} if party else {}),
			}).insert(ignore_permissions=True)
		except Exception as e:
			frappe.db.rollback(save_point="sms_insert")
			return _set(log, "Error", sms_rule=rule.name, error=str(e))
		_set(log, "Matched", sms_rule=rule.name, register_entry=entry.name)
		if not frappe.flags.in_test:
			frappe.db.commit()

	# .get: the column is new, a site that has not migrated yet has no such field
	if rule.auto_post and not log.get("is_sample") and (entry.party or entry.payment_type == "Internal Transfer"):
		frappe.db.savepoint("sms_autopost")
		try:
			entry.submit()
		except Exception as e:
			frappe.db.rollback(save_point="sms_autopost")
			log.db_set("error", str(e))

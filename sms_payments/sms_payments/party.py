import re

import frappe

from sms_payments.sms_payments.parser import normalize_name

TYPE_ORDER = {"Exact": 0, "Contains": 1, "Regex": 2}


def _digits(text):
	d = re.sub(r"\D", "", text or "")
	return d[-9:]


def _matches(rule, name, phone):
	if rule.match_on == "Phone":
		target, value = _digits(phone), _digits(rule.value)
		if not target or not value:
			return False
		if rule.match_type == "Exact":
			return target == value
		if rule.match_type == "Contains":
			return value in target
	else:
		target, value = name, rule.value
		if not target:
			return False
		if rule.match_type == "Exact":
			return target == value
		if rule.match_type == "Contains":
			return value in target
	try:
		return bool(re.search(rule.value, target, re.IGNORECASE))
	except re.error:
		return False


def find_party(payment_type, party_name, party_phone):
	"""Return (party_type, party, rule_name) of the best enabled rule, or None."""
	party_type = {"Receive": "Customer", "Pay": "Supplier"}.get(payment_type)
	if not party_type:
		return None
	name = normalize_name(party_name) if party_name else None
	rules = frappe.get_all(
		"SMS Party Rule",
		filters={"enabled": 1, "party_type": party_type},
		fields=["name", "match_on", "match_type", "value", "party", "priority"],
	)
	# Phone rules before Name rules; then Exact, Contains, Regex; then higher priority
	rules.sort(key=lambda r: (r.match_on != "Phone", TYPE_ORDER[r.match_type], -(r.priority or 0)))
	for r in rules:
		if _matches(r, name, party_phone):
			return party_type, r.party, r.name
	return None


def apply_party_rule_to_drafts(party_rule_name):
	"""Give the new rule's party to matching draft entries (and post them if their SMS Rule auto-posts).

	Entries that came from a hand-picked sample get the party but stay drafts."""
	rule = frappe.get_doc("SMS Party Rule", party_rule_name)
	payment_type = {"Customer": "Receive", "Supplier": "Pay"}[rule.party_type]
	drafts = frappe.get_all(
		"SMS Payment Register",
		filters={"docstatus": 0, "payment_type": payment_type, "party": ("is", "not set")},
		fields=["name", "party_name_in_sms", "party_phone", "sms_rule", "sms_log"],
	)
	updated = []
	for d in drafts:
		found = find_party(payment_type, d.party_name_in_sms, d.party_phone)
		if not found or found[2] != rule.name:
			continue
		frappe.db.savepoint("sms_backfill")
		try:
			entry = frappe.get_doc("SMS Payment Register", d.name)
			entry.update({"party_type": found[0], "party": found[1], "sms_party_rule": rule.name})
			entry.save(ignore_permissions=True)
		except Exception:
			frappe.db.rollback(save_point="sms_backfill")
			frappe.log_error(f"SMS party backfill failed for {d.name}")
			continue
		updated.append(d.name)
		if d.sms_log and frappe.db.get_value("SMS Log", d.sms_log, "is_sample"):
			continue
		if d.sms_rule and frappe.db.get_value("SMS Rule", d.sms_rule, "auto_post"):
			frappe.db.savepoint("sms_autopost")
			try:
				entry.submit()
			except Exception:
				frappe.db.rollback(save_point="sms_autopost")
				frappe.log_error(f"SMS auto-post failed for {d.name}")
	return updated

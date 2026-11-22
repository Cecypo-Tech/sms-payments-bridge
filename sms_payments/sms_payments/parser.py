"""Pure SMS parsing: match an SMS against SMS Rules and extract the payment fields."""

import re
from datetime import datetime

import frappe


class SMSParseError(frappe.ValidationError):
	pass


def parse_amount(text):
	"""'KES. 29,000.00' -> 29000.0"""
	m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
	if not m:
		raise SMSParseError(f"No amount found in {text!r}")
	return float(m.group().replace(",", ""))


def normalize_name(text):
	return re.sub(r"\s+", " ", (text or "").strip().rstrip(".")).strip().upper()


def _parse_time(text):
	text = re.sub(r"\s*([AaPp][Mm])$", r" \1", text.strip())  # "10:15AM" -> "10:15 AM"
	for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
		try:
			return datetime.strptime(text, fmt).time()
		except ValueError:
			pass
	raise SMSParseError(f"Cannot parse time {text!r}")


def extract(rule, sender, body, received_at):
	"""Return the fields a rule extracts from an SMS, or None if it does not apply.

	Reads `rule` through attributes only, so an unsaved Document works too.
	"""
	senders = {s.strip().upper() for s in (rule.senders or "").splitlines() if s.strip()}
	if (sender or "").strip().upper() not in senders:
		return None

	m = re.search(rule.pattern, body or "")
	if not m:
		return None
	groups = m.groupdict()

	if (rule.condition_eval or "").strip():
		ctx = {"sms": frappe._dict(sender=sender, body=body, received_at=received_at), "m": groups}
		try:
			passed = frappe.safe_eval(rule.condition_eval, None, ctx)
		except Exception as e:
			raise SMSParseError(f"Condition error in rule {rule.rule_name}: {e}") from e
		if not passed:
			return None

	if rule.action == "Ignore":
		return {"action": "Ignore"}

	reference = (groups.get("reference") or "").strip().upper()
	if not reference:
		raise SMSParseError(f"reference missing in rule {rule.rule_name}")
	if not (groups.get("amount") or "").strip():
		raise SMSParseError(f"amount missing in rule {rule.rule_name}")

	received_at = frappe.utils.get_datetime(received_at)
	try:
		posting_date = (
			datetime.strptime(groups["date"], rule.date_format or "%d-%m-%Y").date()
			if groups.get("date")
			else received_at.date()
		)
	except ValueError as e:
		raise SMSParseError(f"Cannot parse date {groups['date']!r} in rule {rule.rule_name}: {e}") from e
	posting_time = _parse_time(groups["time"]) if groups.get("time") else received_at.time()

	return {
		"amount": parse_amount(groups.get("amount")),
		"charges": parse_amount(groups["charges"]) if groups.get("charges") else 0.0,
		"reference": reference,
		"party_name": normalize_name(groups["party_name"]) if groups.get("party_name") else None,
		"party_phone": groups.get("party_phone"),
		"posting_date": posting_date,
		"posting_time": posting_time,
	}


def find_rule(sender, body, received_at):
	"""First enabled rule (priority desc, creation asc) that matches -> (rule, extracted)."""
	for name in frappe.get_all(
		"SMS Rule", filters={"enabled": 1}, order_by="priority desc, creation asc", pluck="name"
	):
		rule = frappe.get_doc("SMS Rule", name)
		result = extract(rule, sender, body, received_at)
		if result is not None:
			return rule, result
	return None

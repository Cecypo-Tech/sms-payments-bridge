"""Rule helpers for the desk: suggest a pattern from an SMS, and dry-run a rule against stored logs."""

import hashlib
import re

import frappe

from sms_payments.sms_payments.parser import SMSParseError, extract

NUM = r"[\d,]+(?:\.\d{2})?"
# (kind, regex whose group 1 is the replaced span, named group that replaces it)
CUR = r"(?i:KES|KSH)"  # banks write KES, M-Pesa writes Ksh or KSH
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
# (kind, regex whose matched group is the replaced span, named group that replaces it); first span per kind wins
SPANS = [
	("charges", rf"Transaction cost,\s*{CUR}?\.?\s?({NUM})", rf"(?P<charges>{NUM})"),
	("amount", rf"{CUR}\.?\s?({NUM})|({NUM})\s?{CUR}\b", rf"(?P<amount>{NUM})"),
	(
		"reference",
		r"Ref\.\s*([A-Z0-9]+)|\b((?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{10})\b",
		r"(?P<reference>[A-Z0-9]+)",
	),
	("date", r"(?<!\d)(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})(?!\d)", r"(?P<date>[\d/-]+)"),
	("date", rf"(?<!\d)(\d{{1,2}} {MONTH} \d{{4}})", r"(?P<date>\d{1,2} [A-Za-z]+ \d{4})"),
	("time", r"(\d{1,2}:\d{2}(?:\s?[AP]M)?)", r"(?P<time>[\d:]+(?:\s?[AP]M)?)"),
	("party_name", r"\b(?:from|to) ([A-Z][\w'.&-]*(?: [A-Z][\w'.&-]*)*)", r"(?P<party_name>.+?)"),
	("party_phone", r"(?<!\d)((?:254|0)7\d{8})(?!\d)", r"(?P<party_phone>\d+)"),
]


LITERAL_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


# Text that changes per SMS even in one format: links, the account typed into a paybill payment, and
# transaction ids other than the reference (e.g. the one a reversal undoes).
VOLATILE = re.compile(
	r"https?://\S+|(?<=for account )\S+|\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{10}\b"
)


def _literal(text):
	"""Escape literal text, but let numbers, links and paybill accounts vary from SMS to SMS."""
	return r"\S+".join(
		r"[\d,.]+".join(re.escape(part) for part in LITERAL_NUM.split(chunk)) for chunk in VOLATILE.split(text)
	)


def suggest_date_format(body):
	"""strptime format for the first date in the SMS: 10/11/26 -> %d/%m/%y, 09 Nov 2026 -> %d %b %Y."""
	found = [m for _kind, regex, _ in SPANS if _kind == "date" for m in [re.search(regex, body or "")] if m]
	if not found:
		return None
	date = min(found, key=lambda m: m.start()).group(1)
	if " " in date:
		return "%d %B %Y" if len(date.split()[1]) > 3 else "%d %b %Y"
	sep = re.search(r"[-/]", date).group()
	return f"%d{sep}%m{sep}" + ("%Y" if len(date.split(sep)[-1]) == 4 else "%y")


def suggest_pattern(body):
	"""Regex for an SMS body: recognised spans become named groups, the rest is escaped literally."""
	if not body:
		return ""
	taken, kinds = [], set()  # (start, end, replacement); kinds already placed
	for _kind, regex, group in SPANS:
		if _kind in kinds:
			continue
		for m in re.finditer(regex, body):
			i = m.lastindex
			start, end = m.span(i)
			if _kind == "party_name":
				end = start + len(m.group(i).rstrip("."))
			if not any(start < e and s < end for s, e, _ in taken):
				taken.append((start, end, group))
				kinds.add(_kind)
				break  # first span of each kind wins
	out, pos = [], 0
	for start, end, group in sorted(taken):
		out += [_literal(body[pos:start]), group]
		pos = end
	tail = _literal(body[pos:])
	out.append(tail)
	if not tail and out[-2] == "(?P<party_name>.+?)":
		out[-2] = "(?P<party_name>.+)"  # nothing follows: lazy would capture one character
	return "".join(out)


@frappe.whitelist()
def make_rule_from_log(log_name):
	frappe.has_permission("SMS Log", "read", log_name, throw=True)
	log = frappe.get_doc("SMS Log", log_name)
	return {
		"senders": log.sender,
		"pattern": suggest_pattern(log.body),
		"date_format": suggest_date_format(log.body),
		"rule_name": f"{log.sender} {hashlib.sha1((log.body or '').encode()).hexdigest()[:6]}",
	}


@frappe.whitelist()
def test_rule(rule):
	"""Dry-run an unsaved rule (dict of form values) against the latest 20 logs from its senders."""
	frappe.has_permission("SMS Rule", "read", throw=True)
	values = frappe.parse_json(rule) if isinstance(rule, str) else rule
	try:
		re.compile(values.get("pattern") or "")
	except re.error as e:
		frappe.throw(f"Pattern is not a valid regular expression: {e}")
	doc = frappe.get_doc({**values, "doctype": "SMS Rule"})
	senders = [s.strip() for s in (doc.senders or "").splitlines() if s.strip()]
	if not senders:
		return []
	logs = frappe.get_all(
		"SMS Log", filters={"sender": ("in", senders)}, fields=["name", "sender", "body", "received_at"],
		order_by="received_at desc", limit=20,
	)
	rows = []
	for log in logs:
		row = {"log": log.name, "body": (log.body or "")[:120], "matched": False, "values": None, "error": None}
		try:
			found = extract(doc, log.sender, log.body, log.received_at)
			row["matched"], row["values"] = found is not None, found
		except (SMSParseError, re.error, TypeError) as e:
			row["error"] = str(e)
		rows.append(row)
	return rows


AI_PROMPT = r"""I need a Python regular expression (used with re.search) that pulls the payment details out of a bank or mobile-money SMS.

Rules for the pattern:
- Use named groups, written (?P<name>...). The only names allowed are: amount, reference, party_name, party_phone, date, time, charges.
- amount and reference are required. reference is the transaction code. Leave out any other group the message does not contain.
- amount and charges capture the number only, with its commas and decimals (29,000.00), never the currency.
- party_name is the person or business who paid or was paid. party_phone is their phone number, digits only.
- date and time capture the text exactly as written in the message (time may be 09:47 or 9:47 AM).
- It must match every sample below, and keep matching when the amount, name, reference, date, time and balance are different. Match those parts loosely (for example [\d,]+(?:\.\d+)? for a number and .+? for a name). Keep the fixed words as they are and escape special characters.
- One line. No ^ or $ anchors, no inline flags, no verbose mode, no code around it.

Also give the date format as a Python strptime string for the date group (for example %d-%m-%Y or %d/%m/%y). Write none if there is no date group.

Answer with exactly these two lines and nothing else:
PATTERN: <the regular expression>
DATE FORMAT: <the strptime format, or none>

Sender: {senders}
{samples}"""


@frappe.whitelist()
def ai_prompt(senders, log_name=None):
	"""Text to paste into any AI assistant to get a rule's Pattern: the contract plus up to three real SMS.

	`log_name` (the SMS being looked at) leads the samples. "" when there is no SMS from these senders.
	"""
	frappe.has_permission("SMS Log", "read", throw=True)
	names = [s.strip() for s in (senders or "").splitlines() if s.strip()]
	bodies = []
	if log_name:
		bodies.append(frappe.db.get_value("SMS Log", log_name, "body") or "")
	if names:
		bodies += frappe.get_all(
			"SMS Log", filters={"sender": ("in", names), "name": ("!=", log_name or "")},
			pluck="body", order_by="received_at desc", limit=20,
		)
	bodies = list(dict.fromkeys(b.strip() for b in bodies if (b or "").strip()))[:3]
	if not bodies:
		return ""
	samples = "\n".join(f"\nSample {i}:\n{b}" for i, b in enumerate(bodies, 1))
	return AI_PROMPT.replace("{senders}", ", ".join(names)).replace("{samples}", samples)

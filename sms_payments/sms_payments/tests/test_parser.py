import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from sms_payments.sms_payments.parser import (
	SMSParseError,
	_parse_time,
	extract,
	find_rule,
	normalize_name,
	parse_amount,
)
from sms_payments.sms_payments.tests import bank_account, get_test_company, make_rule

SAMPLE = (
	"Confirmed. KES. 29,000.00 from JANE WANJIKU MWANGI received via M-Pesa "
	"Ref. UKA1B2C3D4 on 09-11-2026 at 09:47. Thank you."
)
PATTERN = (
	r"Confirmed\. KES\. (?P<amount>[\d,]+\.\d{2}) from (?P<party_name>.+?) received via M-Pesa "
	r"Ref\. (?P<reference>\w+) on (?P<date>\d{2}-\d{2}-\d{4}) at (?P<time>\d{2}:\d{2})"
)
RECEIVED = "2026-11-09 09:50:00"


class TestParser(FrappeTestCase):
	def test_parse_amount_formats(self):
		self.assertEqual(parse_amount("KES. 29,000.00"), 29000.0)
		self.assertEqual(parse_amount("Ksh33.00"), 33.0)
		self.assertEqual(parse_amount("KES 1,234"), 1234.0)
		self.assertEqual(parse_amount("Ksh 500"), 500.0)
		self.assertRaises(SMSParseError, parse_amount, "abc")

	def test_normalize_name(self):
		self.assertEqual(normalize_name(" jane  wanjiku mwangi. "), "JANE WANJIKU MWANGI")

	def test_parse_time_12_hour(self):
		# real M-Pesa "sent" SMS use "at 10:15 AM"
		self.assertEqual(_parse_time("10:15 AM"), datetime.time(10, 15))
		self.assertEqual(_parse_time("1:05 PM"), datetime.time(13, 5))
		self.assertEqual(_parse_time("12:30PM"), datetime.time(12, 30))
		self.assertEqual(_parse_time("09:47"), datetime.time(9, 47))

	def test_extract_sample(self):
		rule = make_rule(pattern=PATTERN)
		r = extract(rule, "MPESA", SAMPLE, RECEIVED)
		self.assertEqual(r["amount"], 29000.0)
		self.assertEqual(r["charges"], 0.0)
		self.assertEqual(r["reference"], "UKA1B2C3D4")
		self.assertEqual(r["party_name"], "JANE WANJIKU MWANGI")
		self.assertEqual(r["posting_date"], datetime.date(2026, 11, 9))
		self.assertEqual(r["posting_time"], datetime.time(9, 47))

	def test_extract_charges(self):
		rule = make_rule(
			payment_type="Pay",
			paid_to=None,
			paid_from=bank_account(get_test_company()),
			pattern=r"(?P<reference>\w+) Confirmed. Ksh(?P<amount>[\d,.]+) sent.*"
			r"Transaction cost, Ksh(?P<charges>[\d,.]+)",
		)
		body = "QWE123 Confirmed. Ksh500.00 sent to JOHN. Transaction cost, Ksh33.00."
		self.assertEqual(extract(rule, "MPESA", body, RECEIVED)["charges"], 33.0)

	def test_sender_case_insensitive_and_other_sender_ignored(self):
		rule = make_rule(pattern=PATTERN)
		self.assertIsNotNone(extract(rule, "mpesa", SAMPLE, RECEIVED))
		self.assertIsNone(extract(rule, "SAFARICOM", SAMPLE, RECEIVED))

	def test_condition_eval_false_blocks(self):
		rule = make_rule(pattern=PATTERN, condition_eval="'sent to' in sms.body")
		self.assertIsNone(extract(rule, "MPESA", SAMPLE, RECEIVED))

	def test_date_fallback_to_received_at(self):
		rule = make_rule(pattern=r"Ref\. (?P<reference>\w+).*KES\. (?P<amount>[\d,.]+)")
		body = "Ref. ABC123 KES. 10.00"
		r = extract(rule, "MPESA", body, RECEIVED)
		self.assertEqual(r["posting_date"], datetime.date(2026, 11, 9))
		self.assertEqual(r["posting_time"], datetime.time(9, 50))

	def test_find_rule_priority(self):
		sender = "TESTSND" + frappe.generate_hash(length=6)
		make_rule(pattern=PATTERN, priority=1, senders=sender)
		high = make_rule(pattern=PATTERN, priority=5, senders=sender)
		rule, result = find_rule(sender, SAMPLE, RECEIVED)
		self.assertEqual(rule.name, high.name)
		self.assertEqual(result["reference"], "UKA1B2C3D4")

	def test_broken_condition_raises_parse_error(self):
		rule = make_rule(pattern=PATTERN, condition_eval="m['nope'] > 5")
		self.assertRaises(SMSParseError, extract, rule, "MPESA", SAMPLE, RECEIVED)

	def test_missing_reference_or_amount_raises(self):
		rule = make_rule(pattern=r"Confirmed\. (?P<reference>XX\w+)?(?P<amount>KES\. [\d,.]+)")
		self.assertRaises(SMSParseError, extract, rule, "MPESA", SAMPLE, RECEIVED)
		rule = make_rule(pattern=r"Ref\. (?P<reference>\w+)(?P<amount>Z)?")
		self.assertRaises(SMSParseError, extract, rule, "MPESA", SAMPLE, RECEIVED)

	def test_ignore_rule(self):
		rule = make_rule(action="Ignore", pattern=r"Confirmed", payment_type=None, paid_to=None)
		self.assertEqual(extract(rule, "MPESA", SAMPLE, RECEIVED), {"action": "Ignore"})

	def test_validate_rejects_bad_rules(self):
		self.assertRaises(frappe.ValidationError, make_rule, pattern="(")
		self.assertRaises(frappe.ValidationError, make_rule, pattern=r"(?P<amount>\d+)")
		self.assertRaises(frappe.ValidationError, make_rule, payment_type=None)
		self.assertRaises(frappe.ValidationError, make_rule, company=None)

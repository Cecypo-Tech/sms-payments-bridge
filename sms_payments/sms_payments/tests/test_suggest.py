import re

import frappe
from frappe.tests.utils import FrappeTestCase

from sms_payments.sms_payments.api import add_manual_sms
from sms_payments.sms_payments.suggest import (
	ai_prompt,
	make_rule_from_log,
	suggest_date_format,
	suggest_pattern,
	test_rule,
)
from sms_payments.sms_payments.tests.test_parser import SAMPLE
from sms_payments.sms_payments.tests.test_pipeline import Fixture


class TestSuggest(FrappeTestCase):
	def test_suggest_sent_sms_matches_next_sms(self):
		# balance and account numbers change per SMS: the suggested pattern must not hardcode them
		first = ("UK92X2R33P Confirmed. Ksh1,250.00 sent to KENYA POWER for account 54321 on 10/11/26 "
			"at 10:15 AM. New M-PESA balance is Ksh27,750.00. Transaction cost, Ksh23.00.")
		second = ("UK93Y3S44Q Confirmed. Ksh900.00 sent to KENYA POWER for account 11111 on 11/11/26 "
			"at 2:05 PM. New M-PESA balance is Ksh26,827.00. Transaction cost, Ksh23.00.")
		m = re.search(suggest_pattern(first), second)
		self.assertTrue(m)
		self.assertEqual((m["amount"], m["reference"], m["party_name"], m["date"], m["time"], m["charges"]),
			("900.00", "UK93Y3S44Q", "KENYA POWER", "11/11/26", "2:05 PM", "23.00"))

	def test_suggest_date_format(self):
		self.assertEqual(suggest_date_format(SAMPLE), "%d-%m-%Y")
		self.assertEqual(suggest_date_format("sent on 10/11/26 at 10:15 AM"), "%d/%m/%y")
		self.assertIsNone(suggest_date_format("no date here"))

	def test_suggest_sample_roundtrip(self):
		m = re.search(suggest_pattern(SAMPLE), SAMPLE)
		self.assertEqual(
			m.groupdict(),
			{"amount": "29,000.00", "reference": "UKA1B2C3D4", "party_name": "JANE WANJIKU MWANGI",
				"date": "09-11-2026", "time": "09:47"},
		)

	def test_suggest_escapes_specials(self):
		body = "Paid (Ksh 500) to A+B LTD. Ref. QWE123RTY0 *"
		self.assertTrue(re.search(suggest_pattern(body), body))

	def test_suggest_charges_and_phone(self):
		body = "AB12CD34EF Confirmed. Ksh1,000.00 sent to 0712345678 Transaction cost, Ksh33.00."
		m = re.search(suggest_pattern(body), body)
		self.assertEqual(m["amount"], "1,000.00")
		self.assertEqual(m["charges"], "33.00")
		self.assertEqual(m["party_phone"], "0712345678")
		self.assertEqual(m["reference"], "AB12CD34EF")

	def test_test_rule_reports_matches(self):
		f = Fixture()
		f.log()
		f.log(body="something else entirely")
		doc = f.rule()
		rows = test_rule({"senders": f.sender, "pattern": doc.pattern, "action": "Create Entry"})
		self.assertEqual(len(rows), 2)
		hit = [r for r in rows if r["matched"]]
		self.assertEqual(len(hit), 1)
		self.assertEqual(hit[0]["values"]["reference"], f.ref)

	def test_add_manual_sms(self):
		f = Fixture()
		f.rule()
		at = "2026-11-09 09:50:00"
		name = add_manual_sms(f.sender, f.body(), at)
		log = frappe.get_doc("SMS Log", name)
		self.assertIsNone(log.device)
		self.assertEqual(log.status, "Matched")
		self.assertEqual(add_manual_sms(f.sender, f.body(), at), name)
		self.assertEqual(frappe.db.count("SMS Log", {"sender": f.sender}), 1)

	def test_suggest_name_last_is_greedy(self):
		body = "Received from JANE WANJIKU MWANGI"
		self.assertEqual(re.search(suggest_pattern(body), body)["party_name"], "JANE WANJIKU MWANGI")

	def test_suggest_pattern_empty_body(self):
		self.assertEqual(suggest_pattern(""), "")
		self.assertEqual(suggest_pattern(None), "")

	def test_test_rule_invalid_pattern_is_friendly(self):
		for pattern in ("(", ""):
			try:
				rows = test_rule({"senders": "X", "pattern": pattern, "action": "Create Entry"})
			except frappe.ValidationError:
				continue
			self.assertEqual(rows, [])  # empty pattern: nothing to flag, but must not crash

	def test_make_rule_from_log(self):
		f = Fixture()
		log = f.log()
		r = make_rule_from_log(log.name)
		self.assertEqual(r["senders"], f.sender)
		self.assertTrue(r["rule_name"].startswith(f.sender))
		self.assertTrue(re.search(r["pattern"], log.body))
		self.assertEqual(r["date_format"], suggest_date_format(log.body))

	# Formats from the rules pilot (real phone samples, names/refs/accounts changed).
	EQUITY = ("You have received 275929.00 KES from ACME HARDWARE AND HOUSEHOLDS LIMITED 0********1511 to your "
		"Equity account 0********9198. Ref. A9B1287073F47 on 09 Nov 2026 at 09:20 EAT")
	PAYBILL = ("UKP4Q5R6S7 Confirmed. KSH1.00 sent to Daraja-Sandbox for account FSREALTEST on 10/11/26 at 3:30 PM "
		"New M-PESA balance is KSH12,345.67. Transaction cost, KSH0.00.Amount you can transact within the day is "
		"499,999.00. See all your balances now https://saf.cx/kWQpy")
	REVERSAL = ("UKR1S2T3U4 confirmed. Reversal of transaction UKV5W6X7Y8 has been successfully reversed  on 9/11/26  "
		"at 11:00 PM and Ksh174.00 is credited to your M-PESA account. New M-PESA account balance is Ksh12,346.67.")

	def test_pilot_equity_amount_after_currency_and_month_name_date(self):
		m = re.search(suggest_pattern(self.EQUITY), self.EQUITY)
		self.assertEqual(
			(m["amount"], m["party_name"], m["reference"], m["date"], m["time"]),
			("275929.00", "ACME HARDWARE AND HOUSEHOLDS LIMITED", "A9B1287073F47", "09 Nov 2026", "09:20"),
		)
		self.assertEqual(suggest_date_format(self.EQUITY), "%d %b %Y")

	def test_pilot_paybill_uppercase_ksh_mixed_case_party_and_volatile_text(self):
		p = suggest_pattern(self.PAYBILL)
		m = re.search(p, self.PAYBILL)
		self.assertEqual(
			(m["amount"], m["charges"], m["party_name"], m["reference"], m["date"], m["time"]),
			("1.00", "0.00", "Daraja-Sandbox", "UKP4Q5R6S7", "10/11/26", "3:30 PM"),
		)
		other = (self.PAYBILL.replace("UKP4Q5R6S7", "UKB0000001").replace("KSH1.00", "KSH2,500.00")
			.replace("FSREALTEST", "INV-0042").replace("kWQpy", "Zz9aB"))
		m2 = re.search(p, other)
		self.assertTrue(m2, "next paybill SMS to another account must match")
		self.assertEqual(m2["amount"], "2,500.00")

	def test_pilot_single_digit_day(self):
		m = re.search(suggest_pattern(self.REVERSAL), self.REVERSAL)
		self.assertEqual(m["date"], "9/11/26")
		self.assertEqual(suggest_date_format(self.REVERSAL), "%d/%m/%y")
		other = self.REVERSAL.replace("UKR1S2T3U4", "UKZ9Y8X7W6").replace("UKV5W6X7Y8", "UKP4Q5R6S7")
		self.assertTrue(re.search(suggest_pattern(self.REVERSAL), other), "the reversed transaction id must vary")

	def test_ai_prompt_carries_the_samples_and_the_contract(self):
		f = Fixture()
		log = f.log()
		f.log(body="second message from the same sender")
		text = ai_prompt(f.sender, log.name)
		self.assertIn(log.body, text)
		self.assertIn("second message from the same sender", text)
		self.assertLess(text.index(log.body), text.index("second message"))  # the opened SMS leads
		self.assertEqual(text.count(log.body), 1)
		for word in ("(?P<name>", "amount", "reference", "party_name", "party_phone", "charges", "PATTERN:", "DATE FORMAT:", f.sender):
			self.assertIn(word, text)

	def test_ai_prompt_without_samples_says_so(self):
		self.assertEqual(ai_prompt("NOSUCHSENDER-XYZ"), "")

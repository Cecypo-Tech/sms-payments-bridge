import random

import frappe
from frappe.tests.utils import FrappeTestCase

from sms_payments.sms_payments.party import find_party
from sms_payments.sms_payments.tests import make_customer, make_supplier


def make_party_rule(party_type, party, value, match_on="Name", match_type="Exact", **kw):
	return frappe.get_doc({
		"doctype": "SMS Party Rule", "party_type": party_type, "party": party,
		"value": value, "match_on": match_on, "match_type": match_type, **kw,
	}).insert()


def token():
	return "ZQ" + "".join(c for c in frappe.generate_hash(length=10).upper() if c.isalpha()) + "X"


def rand_digits():
	return str(random.randint(0, 999999)).zfill(6)


class TestParty(FrappeTestCase):
	def test_exact_name(self):
		t = token()
		cust = make_customer("Exact")
		rule = make_party_rule("Customer", cust, f"Jane {t} Mwangi.")
		self.assertEqual(find_party("Receive", f"JANE  {t} MWANGI", None), ("Customer", cust, rule.name))

	def test_phone_beats_name(self):
		t, phone = token(), "0733" + rand_digits()
		supp, cust = make_supplier("PhoneS"), make_customer("NameC")
		sr = make_party_rule("Supplier", supp, phone, "Phone")
		cr = make_party_rule("Customer", cust, t)
		self.assertEqual(find_party("Pay", t, phone), ("Supplier", supp, sr.name))
		self.assertEqual(find_party("Receive", t, phone), ("Customer", cust, cr.name))

	def test_exact_beats_contains_beats_regex(self):
		t = token()
		a, b, c = make_customer("A"), make_customer("B"), make_customer("C")
		make_party_rule("Customer", c, f"{t}.*", match_type="Regex", priority=99)
		rb = make_party_rule("Customer", b, t, match_type="Contains", priority=50)
		name = f"{t} LTD"
		self.assertEqual(find_party("Receive", name, None)[1], b)
		ra = make_party_rule("Customer", a, name)
		self.assertEqual(find_party("Receive", name, None), ("Customer", a, ra.name))
		self.assertEqual(rb.value, t)

	def test_priority_within_type(self):
		t = token()
		lo, hi = make_customer("Lo"), make_customer("Hi")
		make_party_rule("Customer", lo, t, match_type="Contains", priority=1)
		make_party_rule("Customer", hi, t, match_type="Contains", priority=5)
		self.assertEqual(find_party("Receive", f"{t} X", None)[1], hi)

	def test_phone_last_nine_digits(self):
		suffix = rand_digits()
		cust = make_customer("Ph")
		rule = make_party_rule("Customer", cust, f"0722{suffix}", "Phone")
		# 0722xxxxxx is 10 digits; last nine are 722xxxxxx
		self.assertEqual(find_party("Receive", None, f"254722{suffix}"), ("Customer", cust, rule.name))

	def test_disabled_skipped(self):
		t = token()
		make_party_rule("Customer", make_customer("Off"), t, enabled=0)
		self.assertIsNone(find_party("Receive", t, None))

	def test_internal_transfer_none(self):
		t = token()
		make_party_rule("Customer", make_customer("IT"), t)
		self.assertIsNone(find_party("Internal Transfer", t, None))

	def test_bad_regex_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_party_rule("Customer", make_customer("Bad"), "(", match_type="Regex")

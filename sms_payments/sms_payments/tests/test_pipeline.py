import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from sms_payments.sms_payments.pipeline import _process, process_log, reprocess
from sms_payments.sms_payments.tests import (
	bank_account,
	get_test_company,
	make_customer,
	make_rule,
	make_supplier,
)

PATTERN = (
	r"(?P<reference>\w+) Confirmed\. KES (?P<amount>[\d,.]+) from (?P<party_name>[A-Z ]+?) on "
	r"(?P<date>\d+-\d+-\d+)"
)


class Fixture:
	def __init__(self):
		self.sender = "T" + frappe.generate_hash(length=8).upper()
		self.ref = "R" + frappe.generate_hash(length=9).upper()
		self.name = "ZQ" + "".join(c for c in frappe.generate_hash(length=8).upper() if c.isalpha()) + "X"

	def body(self, amount="1,000.00"):
		d = frappe.utils.getdate(today())
		return f"{self.ref} Confirmed. KES {amount} from {self.name} on {d.day}-{d.month}-{d.year}"

	def rule(self, **kw):
		return make_rule(**{"senders": self.sender, "pattern": PATTERN, **kw})

	def log(self, device=None, body=None, is_sample=0):
		return frappe.get_doc({
			"doctype": "SMS Log", "device": device, "is_sample": is_sample, "phone_sms_id": frappe.generate_hash(length=8),
			"sender": self.sender, "body": body or self.body(), "received_at": frappe.utils.now_datetime(),
			"status": "Pending",
		}).insert(ignore_permissions=True)


def device():
	return frappe.get_doc({"doctype": "SMS Device", "device_id": "D" + frappe.generate_hash(length=8)}).insert(
		ignore_permissions=True
	).name


def party_rule(party_type, party, value):
	return frappe.get_doc({
		"doctype": "SMS Party Rule", "party_type": party_type, "party": party, "value": value,
		"match_on": "Name", "match_type": "Exact",
	}).insert()


class TestPipeline(FrappeTestCase):
	def setUp(self):
		self.f = Fixture()

	def test_sample_creates_register_entry(self):
		rule = self.f.rule()
		log = self.f.log()
		process_log(log.name)
		log.reload()
		self.assertEqual(log.status, "Matched")
		self.assertEqual(log.sms_rule, rule.name)
		entry = frappe.get_doc("SMS Payment Register", log.register_entry)
		self.assertEqual((entry.sms_log, entry.reference, entry.amount, entry.docstatus), (log.name, self.f.ref, 1000, 0))

	def test_auto_post_with_party_rule(self):
		self.f.rule(auto_post=1)
		party_rule("Customer", make_customer("AP"), self.f.name)
		log = self.f.log()
		process_log(log.name)
		log.reload()
		entry = frappe.get_doc("SMS Payment Register", log.register_entry)
		self.assertEqual(entry.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Payment Entry", entry.payment_entry, "docstatus"), 1)

	def test_sample_is_never_auto_posted(self):
		self.f.rule(auto_post=1)
		party_rule("Customer", make_customer("SMP"), self.f.name)
		log = self.f.log(is_sample=1)
		process_log(log.name)
		log.reload()
		self.assertEqual(log.status, "Matched")
		self.assertEqual(frappe.db.get_value("SMS Payment Register", log.register_entry, "docstatus"), 0)

	def test_party_rule_fills_sample_draft_without_posting(self):
		self.f.rule(auto_post=1)
		log = self.f.log(is_sample=1)
		process_log(log.name)
		entry = frappe.get_doc("SMS Payment Register", frappe.db.get_value("SMS Log", log.name, "register_entry"))
		cust = make_customer("SMPB")
		party_rule("Customer", cust, self.f.name)
		entry.reload()
		self.assertEqual((entry.docstatus, entry.party), (0, cust))

	def test_second_device_duplicate(self):
		self.f.rule()
		a, b = self.f.log(device()), self.f.log(device())
		process_log(a.name)
		process_log(b.name)
		a.reload()
		b.reload()
		self.assertEqual(b.status, "Duplicate")
		self.assertEqual(b.register_entry, a.register_entry)
		self.assertEqual(frappe.db.count("SMS Payment Register", {"reference": self.f.ref}), 1)

	def test_same_reference_different_amount_is_error(self):
		self.f.rule()
		a, b = self.f.log(), self.f.log(body=self.f.body("2,000.00"))
		process_log(a.name)
		process_log(b.name)
		b.reload()
		self.assertEqual(b.status, "Error")
		self.assertIn("different amount or type", b.error)

	def test_existing_payment_entry_reference_is_duplicate(self):
		company = get_test_company()
		self.f.rule()
		pe = frappe.get_doc({
			"doctype": "Payment Entry", "payment_type": "Receive", "company": company,
			"posting_date": today(), "party_type": "Customer", "party": make_customer("PE"),
			"paid_to": bank_account(company), "paid_amount": 1000, "received_amount": 1000,
			"source_exchange_rate": 1, "target_exchange_rate": 1, "reference_no": self.f.ref,
			"reference_date": today(),
		}).insert(ignore_permissions=True)
		pe.submit()
		log = self.f.log()
		process_log(log.name)
		log.reload()
		self.assertEqual((log.status, log.payment_entry), ("Duplicate", pe.name))
		self.assertFalse(frappe.db.exists("SMS Payment Register", {"reference": self.f.ref}))

	def test_unmatched_then_rule_then_reprocess(self):
		log = self.f.log()
		process_log(log.name)
		self.assertEqual(frappe.db.get_value("SMS Log", log.name, "status"), "Unmatched")
		self.f.rule()
		process_log(log.name)
		self.assertEqual(frappe.db.get_value("SMS Log", log.name, "status"), "Matched")

	def test_parse_error_names_rule(self):
		rule = self.f.rule(pattern=r"(?P<reference>\w+) Confirmed\. KES (?P<amount>\d*)")
		log = self.f.log(body=f"{self.f.ref} Confirmed. KES ")
		process_log(log.name)
		log.reload()
		self.assertEqual(log.status, "Error")
		self.assertIn(rule.rule_name, log.error)

	def test_auto_post_failure_keeps_draft(self):
		company = get_test_company()
		acct = frappe.get_doc({
			"doctype": "Account", "account_name": "SMS Test Bank " + frappe.generate_hash(length=5),
			"parent_account": frappe.db.get_value("Account", bank_account(company), "parent_account"),
			"company": company, "account_type": "Bank",
			"account_currency": frappe.get_cached_value("Company", company, "default_currency"),
		}).insert(ignore_permissions=True).name
		self.f.rule(auto_post=1, paid_to=acct)
		party_rule("Customer", make_customer("F"), self.f.name)
		frappe.db.set_value("Account", acct, "disabled", 1)
		log = self.f.log()
		process_log(log.name)
		log.reload()
		self.assertEqual(log.status, "Matched")
		self.assertTrue(log.error)
		self.assertEqual(frappe.db.get_value("SMS Payment Register", log.register_entry, "docstatus"), 0)
		self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": self.f.ref}))

	def test_insert_failure_is_error_not_pending(self):
		rule = self.f.rule()
		# a rule pointing at a vanished account: the register insert fails link validation
		frappe.db.set_value("SMS Rule", rule.name, "paid_to", "No Such Account " + self.f.ref)
		log = self.f.log()
		process_log(log.name)
		log.reload()
		self.assertEqual(log.status, "Error")
		self.assertTrue(log.error)
		self.assertFalse(frappe.db.exists("SMS Payment Register", {"reference": self.f.ref}))

	def test_pay_supplier(self):
		company = get_test_company()
		paid_from = bank_account(company)
		self.f.rule(payment_type="Pay", paid_to=None, paid_from=paid_from, auto_post=1)
		supplier = make_supplier("PS")
		party_rule("Supplier", supplier, self.f.name)
		log = self.f.log()
		process_log(log.name)
		log.reload()
		entry = frappe.get_doc("SMS Payment Register", log.register_entry)
		pe = frappe.get_doc("Payment Entry", entry.payment_entry)
		self.assertEqual((pe.payment_type, pe.party_type, pe.party), ("Pay", "Supplier", supplier))


class TestReprocessAndBackfill(FrappeTestCase):
	def setUp(self):
		self.f = Fixture()

	def test_reprocess_skips_matched(self):
		self.f.rule()
		matched = self.f.log()
		process_log(matched.name)
		unmatched = self.f.log(body="nothing to see")
		process_log(unmatched.name)
		self.assertEqual(frappe.db.get_value("SMS Log", unmatched.name, "status"), "Unmatched")
		self.assertEqual(reprocess([matched.name, unmatched.name]), 1)
		self.assertEqual(frappe.db.count("SMS Payment Register", {"reference": self.f.ref}), 1)

	def test_party_rule_backfills_drafts(self):
		self.f.rule(auto_post=1)
		log = self.f.log()
		process_log(log.name)
		entry = frappe.get_doc("SMS Payment Register", frappe.db.get_value("SMS Log", log.name, "register_entry"))
		self.assertEqual(entry.docstatus, 0)
		cust = make_customer("Backfill")
		party_rule("Customer", cust, self.f.name)
		entry.reload()
		self.assertEqual((entry.docstatus, entry.party), (1, cust))

	def test_party_rule_rejects_match_all_values(self):
		for match_on, value in (("Name", "."), ("Phone", "abc")):
			doc = frappe.get_doc({
				"doctype": "SMS Party Rule", "party_type": "Customer", "party": "x", "value": value,
				"match_on": match_on, "match_type": "Contains",
			})
			self.assertRaises(frappe.ValidationError, doc.insert)

	def test_reprocess_all_and_permission(self):
		pending = self.f.log()
		err = self.f.log()
		err.db_set("status", "Error")
		done = self.f.log()
		done.db_set("status", "Matched")
		n = reprocess()
		self.assertGreaterEqual(n, 2)
		self.assertEqual(reprocess([pending.name, err.name, done.name]), 2)
		user = "sms-plain-" + frappe.generate_hash(length=6) + "@example.com"
		frappe.get_doc({"doctype": "User", "email": user, "first_name": "Plain", "send_welcome_email": 0,
			"roles": [{"role": "Accounts User"}]}).insert(ignore_permissions=True)
		frappe.set_user(user)
		try:
			self.assertRaises(frappe.PermissionError, reprocess, [pending.name])
		finally:
			frappe.set_user("Administrator")

	def test_backfill_leaves_non_matching_draft(self):
		self.f.rule()
		log = self.f.log()
		process_log(log.name)
		entry = frappe.db.get_value("SMS Log", log.name, "register_entry")
		party_rule("Customer", make_customer("Other"), "NOBODY" + self.f.name)
		self.assertFalse(frappe.db.get_value("SMS Payment Register", entry, "party"))

	def test_backfill_failure_isolation(self):
		company = get_test_company()
		good_acct = bank_account(company)  # before the new account exists, so the two rules differ
		acct = frappe.get_doc({
			"doctype": "Account", "account_name": "SMS Test Bank " + frappe.generate_hash(length=5),
			"parent_account": frappe.db.get_value("Account", good_acct, "parent_account"),
			"company": company, "account_type": "Bank",
			"account_currency": frappe.get_cached_value("Company", company, "default_currency"),
		}).insert(ignore_permissions=True).name
		bad, good = Fixture(), Fixture()
		bad.rule(auto_post=1, paid_to=acct)
		good.rule(auto_post=1, paid_to=good_acct)
		bad_log, good_log = bad.log(), good.log()
		process_log(bad_log.name)
		process_log(good_log.name)
		frappe.db.set_value("Account", acct, "disabled", 1)
		cust = make_customer("Iso")
		frappe.get_doc({
			"doctype": "SMS Party Rule", "party_type": "Customer", "party": cust, "match_on": "Name",
			"match_type": "Regex", "value": f"{bad.name}|{good.name}",
		}).insert()
		get = lambda log: frappe.db.get_value(
			"SMS Payment Register", frappe.db.get_value("SMS Log", log.name, "register_entry"),
			["docstatus", "party"], as_dict=True,
		)
		self.assertEqual((get(bad_log).docstatus, get(bad_log).party), (0, cust))
		self.assertEqual((get(good_log).docstatus, get(good_log).party), (1, cust))

	def test_party_rule_rejects_empty_regex(self):
		doc = frappe.get_doc({"doctype": "SMS Party Rule", "party_type": "Customer", "party": "x",
			"value": "", "match_on": "Name", "match_type": "Regex"})
		self.assertRaises(frappe.ValidationError, doc.insert)


class TestFinalReview(FrappeTestCase):
	def setUp(self):
		self.f = Fixture()

	def test_stale_log_processed_twice_stays_matched(self):
		self.f.rule()
		log = self.f.log()
		stale = frappe.get_doc("SMS Log", log.name)  # a second worker holding the Pending copy
		process_log(log.name)
		_process(stale)
		self.assertEqual(frappe.db.get_value("SMS Log", log.name, "status"), "Matched")
		self.assertEqual(frappe.db.count("SMS Payment Register", {"reference": self.f.ref}), 1)

	def test_rule_rejects_foreign_currency_account(self):
		company = get_test_company()
		foreign = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 0, "account_type": "Bank",
				"account_currency": ("!=", frappe.get_cached_value("Company", company, "default_currency"))},
		)
		if not foreign:
			self.skipTest("no foreign-currency bank account")
		with self.assertRaises(frappe.ValidationError):
			make_rule(paid_to=foreign)

	def test_enabling_party_rule_backfills_draft(self):
		self.f.rule()
		log = self.f.log()
		process_log(log.name)
		entry_name = frappe.db.get_value("SMS Log", log.name, "register_entry")
		cust = make_customer("Enable")
		pr = party_rule("Customer", cust, self.f.name)
		pr.db_set("enabled", 0)
		frappe.db.set_value("SMS Payment Register", entry_name, "party", None)
		frappe.db.set_value("SMS Payment Register", entry_name, "party_type", None)
		pr.reload()
		pr.enabled = 1
		pr.save()
		self.assertEqual(frappe.db.get_value("SMS Payment Register", entry_name, "party"), cust)

	def test_reprocess_is_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[reprocess], ["POST"])

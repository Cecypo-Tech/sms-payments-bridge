import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from sms_payments.sms_payments.tests import (
	bank_account,
	get_test_company,
	make_customer,
	make_supplier,
)


def expense_account(company):
	return frappe.db.get_value(
		"Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name"
	)


def second_bank_account(company, other):
	"""A non-group Bank account in the same currency as `other`, created if the company lacks one."""
	currency = frappe.get_cached_value("Company", company, "default_currency")
	found = frappe.db.get_value(
		"Account",
		{
			"company": company, "account_type": "Bank", "is_group": 0,
			"account_currency": currency, "name": ("!=", other or ""),
		},
		"name",
	)
	if found:
		return found
	return frappe.get_doc({
		"doctype": "Account",
		"account_name": "SMS Test Bank " + frappe.generate_hash(length=5),
		"parent_account": frappe.db.get_value("Account", bank_account(company), "parent_account"),
		"company": company,
		"account_type": "Bank",
		"account_currency": currency,
	}).insert(ignore_permissions=True).name


def make_register(payment_type="Receive", amount=1000, charges=0, with_charges_account=True, **kw):
	company = get_test_company()
	values = {
		"doctype": "SMS Payment Register",
		"reference": "T" + frappe.generate_hash(length=9).upper(),
		"amount": amount,
		"charges": charges,
		"posting_date": today(),
		"payment_type": payment_type,
		"company": company,
		"sender": "MPESA",
		"raw_message": "test message",
	}
	if payment_type in ("Receive", "Internal Transfer"):
		values["paid_to"] = bank_account(company)
	if payment_type == "Internal Transfer":
		# the arbitrary first bank account can be a foreign-currency one; use a company-currency pair
		values["paid_to"] = second_bank_account(company, None)
	if payment_type == "Pay":
		values["paid_from"] = bank_account(company)
	if payment_type == "Internal Transfer":
		values["paid_from"] = second_bank_account(company, values["paid_to"])
	if with_charges_account:
		values["charges_account"] = expense_account(company)
	if payment_type == "Receive":
		values.update(party_type="Customer", party=make_customer("Reg"))
	elif payment_type == "Pay":
		values.update(party_type="Supplier", party=make_supplier("Reg"))
	values.update(kw)
	return frappe.get_doc(values).insert()


class TestRegister(FrappeTestCase):
	def gl(self, pe):
		"""account -> (debit, credit) summed over the PE's live GL rows."""
		out = {}
		for row in frappe.get_all(
			"GL Entry", {"voucher_no": pe.name, "is_cancelled": 0}, ["account", "debit", "credit"]
		):
			d, c = out.get(row.account, (0, 0))
			out[row.account] = (d + row.debit, c + row.credit)
		return out

	def test_receive_with_charges(self):
		r = make_register("Receive", 29000, 33, reference="UKA1B2C3D4")
		r.submit()
		pe = frappe.get_doc("Payment Entry", r.payment_entry)
		self.assertEqual(pe.docstatus, 1)
		self.assertEqual(pe.deductions[0].amount, 33)
		self.assertEqual(pe.unallocated_amount, 29000)
		self.assertEqual(pe.difference_amount, 0)
		self.assertEqual(pe.reference_no, r.reference)
		gl = self.gl(pe)
		self.assertEqual(gl[pe.paid_from][1], 29000)
		self.assertEqual(gl[r.paid_to][0], 28967)
		self.assertEqual(gl[r.charges_account][0], 33)

	def test_pay_with_charges(self):
		r = make_register("Pay", 1000, 33)
		r.submit()
		pe = frappe.get_doc("Payment Entry", r.payment_entry)
		self.assertEqual(pe.unallocated_amount, 1000)
		self.assertEqual(pe.difference_amount, 0)
		gl = self.gl(pe)
		self.assertEqual(gl[pe.paid_to][0], 1000)
		self.assertEqual(gl[r.paid_from][1], 1033)
		self.assertEqual(gl[r.charges_account][0], 33)

	def test_charges_ignored_without_account(self):
		r = make_register("Receive", 1000, 33, with_charges_account=False)
		r.submit()
		pe = frappe.get_doc("Payment Entry", r.payment_entry)
		self.assertEqual(pe.paid_amount, 1000)
		self.assertFalse(pe.deductions)

	def test_internal_transfer(self):
		r = make_register("Internal Transfer", 500)
		r.submit()
		pe = frappe.get_doc("Payment Entry", r.payment_entry)
		self.assertEqual(pe.payment_type, "Internal Transfer")
		self.assertEqual((pe.paid_from, pe.paid_to), (r.paid_from, r.paid_to))

	def test_submit_requires_party_for_receive(self):
		r = make_register("Receive", 100, party_type="", party=None)
		self.assertRaises(frappe.ValidationError, r.submit)

	def test_party_type_must_match_payment_type(self):
		self.assertRaises(
			frappe.ValidationError,
			make_register,
			"Receive",
			100,
			party_type="Supplier",
			party=make_supplier("Bad"),
		)

	def test_duplicate_reference_rejected(self):
		r = make_register("Receive", 100)
		self.assertRaises(
			frappe.DuplicateEntryError, make_register, "Receive", 100, reference=r.reference
		)

	def test_reference_reusable_after_cancel(self):
		r = make_register("Receive", 100)
		r.submit()
		r.cancel()
		make_register("Receive", 100, reference=r.reference)

	def test_cancel_cancels_payment_entry(self):
		r = make_register("Receive", 100)
		r.submit()
		r.cancel()
		self.assertEqual(frappe.db.get_value("Payment Entry", r.payment_entry, "docstatus"), 2)

	def test_internal_transfer_with_charges(self):
		r = make_register("Internal Transfer", 1000, 33)
		r.submit()
		pe = frappe.get_doc("Payment Entry", r.payment_entry)
		self.assertEqual((pe.paid_amount, pe.received_amount), (1033, 1000))
		self.assertEqual(len(pe.deductions), 1)
		self.assertEqual((pe.deductions[0].account, pe.deductions[0].amount), (r.charges_account, 33))
		self.assertEqual(pe.difference_amount, 0)
		gl = self.gl(pe)
		self.assertEqual(gl[r.paid_from][1], 1033)
		self.assertEqual(gl[r.paid_to][0], 1000)
		self.assertEqual(gl[r.charges_account][0], 33)

	def test_create_payment_entry_rejected_on_draft(self):
		r = make_register("Receive", 100)
		self.assertRaises(frappe.ValidationError, r.create_payment_entry)
		self.assertFalse(r.payment_entry)

	def test_submit_rejects_bad_amounts(self):
		for amount, charges in ((0, 0), (-5, 0), (100, 100), (100, 150)):
			r = make_register("Receive", amount, charges)
			self.assertRaises(frappe.ValidationError, r.submit)

	def test_submit_requires_party_type(self):
		r = make_register("Receive", 100)
		r.party_type = ""
		self.assertRaises(frappe.ValidationError, r.submit)

	def test_preset_payment_entry_cannot_skip_posting(self):
		r = make_register("Receive")
		r.payment_entry = "ACC-PAY-FAKE"
		with self.assertRaises(frappe.ValidationError):
			r.submit()

	def test_foreign_currency_bank_rejected_at_posting(self):
		company = get_test_company()
		foreign = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 0, "account_type": "Bank",
				"account_currency": ("!=", frappe.get_cached_value("Company", company, "default_currency"))},
		)
		if not foreign:
			self.skipTest("no foreign-currency bank account")
		r = make_register("Receive")
		r.paid_to = foreign
		with self.assertRaises(frappe.ValidationError):
			r.submit()

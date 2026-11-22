import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

PARTY_TYPE = {"Receive": "Customer", "Pay": "Supplier"}


class SMSPaymentRegister(Document):
	# Cancelling the register cancels its Payment Entry; don't block on that link.
	ignore_linked_doctypes = ("Payment Entry",)

	def validate(self):
		expected = PARTY_TYPE.get(self.payment_type)
		# drafts may have no party yet (unmatched SMS); before_submit requires it
		if self.party_type and self.party_type != expected:
			frappe.throw(
				_("Party Type must be {0} for payment type {1}").format(
					expected or _("empty"), self.payment_type
				)
			)

		exclude = [self.name, self.amended_from]
		if frappe.db.exists(
			"SMS Payment Register",
			{
				"company": self.company,
				"reference": self.reference,
				"docstatus": ("!=", 2),
				"name": ("not in", [x for x in exclude if x]),
			},
		):
			frappe.throw(
				_("An SMS Payment Register entry with reference {0} already exists for {1}").format(
					self.reference, self.company
				),
				frappe.DuplicateEntryError,
			)

	def before_submit(self):
		if not (self.company and self.posting_date):
			frappe.throw(_("Company and Posting Date are required"))
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero"))
		if self.charges_account and 0 < flt(self.charges) and flt(self.charges) >= flt(self.amount):
			frappe.throw(_("Charges must be less than the amount"))
		if self.payment_type in PARTY_TYPE and not (self.party_type and self.party):
			frappe.throw(_("Party Type and Party are required to submit a {0} entry").format(self.payment_type))
		if self.payment_type in ("Receive", "Internal Transfer") and not self.paid_to:
			frappe.throw(_("Account Paid To is required for payment type {0}").format(self.payment_type))
		if self.payment_type in ("Pay", "Internal Transfer") and not self.paid_from:
			frappe.throw(_("Account Paid From is required for payment type {0}").format(self.payment_type))

	def on_submit(self):
		self._create_payment_entry()

	def on_cancel(self):
		# No try/except: if the Payment Entry cannot be cancelled, the cancel must fail.
		if self.payment_entry and frappe.db.get_value("Payment Entry", self.payment_entry, "docstatus") == 1:
			frappe.get_doc("Payment Entry", self.payment_entry).cancel()

	@frappe.whitelist()
	def create_payment_entry(self):
		self.check_permission("submit")
		if self.docstatus != 1:
			frappe.throw(_("Submit the register entry before creating a Payment Entry"))
		return self._create_payment_entry()

	def _check_single_currency(self):
		currency = frappe.get_cached_value("Company", self.company, "default_currency")
		accounts = [self.paid_to, self.paid_from, self.charges_account if flt(self.charges) > 0 else None]
		if self.payment_type in PARTY_TYPE:
			from erpnext.accounts.party import get_party_account

			accounts.append(get_party_account(self.party_type, self.party, self.company))
		for account in filter(None, accounts):
			acc_currency = frappe.get_cached_value("Account", account, "account_currency")
			if acc_currency and acc_currency != currency:
				frappe.throw(
					_("Account {0} is in {1}; only company currency ({2}) is supported").format(
						account, acc_currency, currency
					)
				)

	def _create_payment_entry(self):
		if self.payment_entry:
			frappe.throw(_("Payment Entry {0} already exists").format(self.payment_entry))

		self._check_single_currency()
		amount = flt(self.amount)
		charges = flt(self.charges) if self.charges_account and flt(self.charges) > 0 else 0
		paid, received = {
			"Receive": (amount - charges, amount - charges),
			"Pay": (amount + charges, amount + charges),
			"Internal Transfer": (amount + charges, amount),
		}[self.payment_type]

		pe = frappe.get_doc({
			"doctype": "Payment Entry",
			"payment_type": self.payment_type,
			"company": self.company,
			"posting_date": self.posting_date,
			"mode_of_payment": self.mode_of_payment or None,
			"paid_from": self.paid_from if self.payment_type != "Receive" else None,
			"paid_to": self.paid_to if self.payment_type != "Pay" else None,
			"paid_amount": paid,
			"received_amount": received,
			"source_exchange_rate": 1,
			"target_exchange_rate": 1,
			"reference_no": self.reference,
			"reference_date": self.posting_date,
			"remarks": f"From SMS {self.sender}: {self.raw_message}"[:500],
		})
		if self.payment_type in PARTY_TYPE:
			pe.party_type, pe.party = self.party_type, self.party
		if charges:
			pe.append("deductions", {
				"account": self.charges_account,
				"cost_center": self.charges_cost_center
				or frappe.get_cached_value("Company", self.company, "cost_center"),
				"amount": charges,
				# ERPNext treats paid - received on an Internal Transfer as exchange gain/loss and keeps
				# one such row in sync; flag ours so it is reused (and not duplicated) on the charges account.
				"is_exchange_gain_loss": 1 if self.payment_type == "Internal Transfer" else 0,
			})
		pe.insert(ignore_permissions=True)
		pe.submit()
		self.db_set("payment_entry", pe.name)
		return pe.name

import re

import frappe
from frappe import _
from frappe.model.document import Document


class SMSRule(Document):
	def validate(self):
		try:
			compiled = re.compile(self.pattern or "")
		except re.error as e:
			frappe.throw(_("Pattern is not a valid regular expression: {0}").format(e))

		if self.action != "Create Entry":
			return

		for fieldname in ("payment_type", "company"):
			if not self.get(fieldname):
				frappe.throw(_("{0} is required for a Create Entry rule").format(_(self.meta.get_label(fieldname))))

		for group in ("amount", "reference"):
			if group not in compiled.groupindex:
				frappe.throw(_("Pattern must have a named group (?P<{0}>...)").format(group))

		needed = {"Receive": ["paid_to"], "Pay": ["paid_from"], "Internal Transfer": ["paid_to", "paid_from"]}
		for fieldname in needed.get(self.payment_type, []):
			if not self.get(fieldname):
				frappe.throw(
					_("{0} is required for payment type {1}").format(
						_(self.meta.get_label(fieldname)), self.payment_type
					)
				)

		currency = frappe.get_cached_value("Company", self.company, "default_currency")
		for fieldname in ("paid_to", "paid_from", "charges_account"):
			account = self.get(fieldname)
			if not account:
				continue
			acc_company, acc_currency = frappe.db.get_value("Account", account, ["company", "account_currency"])
			if acc_company != self.company:
				frappe.throw(
					_("{0} {1} does not belong to company {2}").format(
						_(self.meta.get_label(fieldname)), account, self.company
					)
				)
			if acc_currency and acc_currency != currency:
				frappe.throw(
					_("{0} {1} must be in the company currency {2}, not {3}").format(
						_(self.meta.get_label(fieldname)), account, currency, acc_currency
					)
				)

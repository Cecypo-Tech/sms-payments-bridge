import re

import frappe
from frappe import _
from frappe.model.document import Document

from sms_payments.sms_payments.parser import normalize_name


class SMSPartyRule(Document):
	def validate(self):
		if self.match_type == "Regex":
			try:
				re.compile(self.value or "")
			except re.error as e:
				frappe.throw(_("Value is not a valid regular expression: {0}").format(e))
		elif self.match_on == "Name":
			self.value = normalize_name(self.value)
		# a value that normalises to nothing would match every payer
		if self.match_type == "Regex":
			if not (self.value or "").strip():
				frappe.throw(_("Value is required"))
		elif self.match_on == "Name":
			if not self.value:
				frappe.throw(_("Value must be a name"))
		elif not re.search(r"\d", self.value or ""):
			frappe.throw(_("Value must contain digits"))

	def after_insert(self):
		self._backfill()

	def on_update(self):
		if self.is_new() or self.flags.in_insert:
			return  # after_insert handles it
		changed = any(
			self.has_value_changed(f)
			for f in ("enabled", "value", "match_on", "match_type", "party_type", "party")
		)
		if self.enabled and changed:
			self._backfill()

	def _backfill(self):
		from sms_payments.sms_payments.party import apply_party_rule_to_drafts

		apply_party_rule_to_drafts(self.name)

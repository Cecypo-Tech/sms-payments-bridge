import frappe
from frappe.tests.utils import FrappeTestCase

from sms_payments.sms_payments import release_module_from_bank_app


class TestInstall(FrappeTestCase):
	def test_releases_module_left_by_the_bank_app(self):
		frappe.db.set_value("Module Def", "SMS Payments", "app_name", "cecypo_bank_integrations")
		release_module_from_bank_app()
		self.assertFalse(frappe.db.exists("Module Def", "SMS Payments"))
		self.assertTrue(frappe.db.exists("DocType", "SMS Payment Register"))

	def test_keeps_its_own_module(self):
		release_module_from_bank_app()
		self.assertEqual(frappe.db.get_value("Module Def", "SMS Payments", "app_name"), "sms_payments")

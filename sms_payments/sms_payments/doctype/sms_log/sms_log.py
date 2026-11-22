import frappe
from frappe.model.document import Document


class SMSLog(Document):
	pass


def on_doctype_update():
	frappe.db.add_unique("SMS Log", ["device", "phone_sms_id"])

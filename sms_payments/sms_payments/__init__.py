

def ensure_role():
	"""The phone's API user holds this role (api._check_caller); no doctype grants it, so nothing else creates it."""
	import frappe

	if not frappe.db.exists("Role", "SMS Gateway"):
		frappe.get_doc({"doctype": "Role", "role_name": "SMS Gateway", "desk_access": 0}).insert(ignore_permissions=True)

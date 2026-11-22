

def ensure_role():
	"""The phone's API user holds this role (api._check_caller); no doctype grants it, so nothing else creates it."""
	import frappe

	if not frappe.db.exists("Role", "SMS Gateway"):
		frappe.get_doc({"doctype": "Role", "role_name": "SMS Gateway", "desk_access": 0}).insert(ignore_permissions=True)


def release_module_from_bank_app():
	"""Sites that had kenya-bank-integrations keep Module Def "SMS Payments" under that app, which makes
	install-app fail with a duplicate. Drop that row (a raw delete leaves the DocTypes alone); install recreates it."""
	import frappe

	frappe.db.delete("Module Def", {"name": "SMS Payments", "app_name": "cecypo_bank_integrations"})

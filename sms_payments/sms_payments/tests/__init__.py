import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import today


def get_test_company():
	"""A company with a non-group Bank account and a fiscal year covering today."""
	for company in frappe.get_all("Company", pluck="name"):
		if not frappe.db.exists("Account", {"account_type": "Bank", "company": company, "is_group": 0}):
			continue
		if get_fiscal_year(today(), company=company, raise_on_missing=False, verbose=0):
			return company
	return frappe.db.get_value("Company", {}, "name")


def bank_account(company):
	"""A non-group Bank account in the company currency (a foreign-currency one breaks Payment Entries)."""
	return frappe.db.get_value(
		"Account",
		{
			"account_type": "Bank", "company": company, "is_group": 0, "disabled": 0,
			"account_currency": frappe.get_cached_value("Company", company, "default_currency"),
		},
		"name",
	)


def make_rule(**kw):
	"""Insert an SMS Rule (a Receive rule on the test company by default)."""
	company = kw.pop("company") if "company" in kw else get_test_company()
	values = {
		"doctype": "SMS Rule",
		"rule_name": f"Test Rule {frappe.generate_hash(length=8)}",
		"senders": "MPESA",
		"action": "Create Entry",
		"pattern": r"Ref\. (?P<reference>\w+) KES (?P<amount>[\d,.]+)",
		"payment_type": "Receive",
		"company": company,
		"paid_to": bank_account(company),
	}
	values.update(kw)
	return frappe.get_doc(values).insert()


def make_customer(name):
	return frappe.get_doc({
		"doctype": "Customer",
		"customer_name": f"{name} {frappe.generate_hash(length=6)}",
		"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
		"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
	}).insert(ignore_permissions=True).name


def make_supplier(name):
	return frappe.get_doc({
		"doctype": "Supplier",
		"supplier_name": f"{name} {frappe.generate_hash(length=6)}",
		"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
	}).insert(ignore_permissions=True).name

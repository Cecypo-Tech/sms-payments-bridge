"""
after_request hook - sanitizes Frappe error responses for the SMS Payments API.

When Frappe catches an unhandled exception (including framework-level errors such as
invalid request JSON), it returns a response body containing internal fields:
  exception, exc_type, exc, _server_messages

These disclose stack traces and framework internals to external callers. This hook
detects those fields on any /api/method/sms_payments.* path, logs the
full detail to the ERPNext Error Log, and replaces the body with a generic message.
"""

import json

import frappe

_API_PREFIX = "/api/method/sms_payments."

# Fields present in Frappe's unhandled-exception JSON response
_FRAPPE_INTERNAL_KEYS = frozenset({"exception", "exc_type", "exc", "_server_messages"})


def after_request(response, request):
	if not request.path.startswith(_API_PREFIX):
		return

	if response.status_code < 400:
		return

	try:
		body = response.get_data(as_text=True)
		data = json.loads(body)
	except Exception:
		return

	if not _FRAPPE_INTERNAL_KEYS.intersection(data):
		return

	# Log the full detail internally before sanitizing
	try:
		frappe.log_error(
			title=f"SMS Payments API unhandled error - {request.path}",
			message=body,
		)
		frappe.db.commit()
	except Exception:
		pass

	sanitized = json.dumps({"message": "Invalid request - see error log for details"})
	response.set_data(sanitized)
	response.content_type = "application/json"

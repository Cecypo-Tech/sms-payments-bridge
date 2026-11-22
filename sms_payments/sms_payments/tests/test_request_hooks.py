import json
from types import SimpleNamespace

from frappe.tests.utils import FrappeTestCase
from werkzeug.wrappers import Response

from sms_payments.utils.request_hooks import after_request


class TestRequestHooks(FrappeTestCase):
	def _call(self, path, status, body):
		resp = Response(json.dumps(body), status=status, mimetype="application/json")
		after_request(resp, SimpleNamespace(path=path))
		return json.loads(resp.get_data(as_text=True))

	def test_strips_internals_on_app_path(self):
		out = self._call(
			"/api/method/sms_payments.sms_payments.api.config",
			500,
			{"exception": "boom", "exc_type": "X", "exc": "trace"},
		)
		self.assertFalse({"exception", "exc_type", "exc"} & out.keys())

	def test_leaves_other_paths(self):
		body = {"exception": "boom"}
		self.assertEqual(self._call("/api/method/frappe.ping", 500, body), body)

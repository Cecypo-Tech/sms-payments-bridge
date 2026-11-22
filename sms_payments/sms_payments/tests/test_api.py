from datetime import UTC, datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from sms_payments.sms_payments import api
from sms_payments.sms_payments.tests import make_customer
from sms_payments.sms_payments.tests.test_pipeline import Fixture, device, party_rule


class TestAPI(FrappeTestCase):
	def setUp(self):
		self.f = Fixture()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		for field, value in (("sms_enabled", 1), ("sms_extra_senders", ""), ("sms_backfill_days", 3)):
			old = frappe.db.get_single_value("SMS Payments Settings", field)
			self.addCleanup(frappe.db.set_single_value, "SMS Payments Settings", field, old)
			frappe.db.set_single_value("SMS Payments Settings", field, value)

	def msg(self, body=None, **kw):
		return {"phone_sms_id": frappe.generate_hash(length=8), "sender": self.f.sender,
			"body": body or self.f.body(), "received_at_ms": 1_700_000_000_000, "sim_slot": 0, **kw}

	def test_backfill_defaults_to_three_on_a_fresh_install(self):
		frappe.db.delete("Singles", {"doctype": "SMS Payments Settings", "field": "sms_backfill_days"})
		frappe.clear_cache(doctype="SMS Payments Settings")
		res = api.get_config("D" + frappe.generate_hash(length=8))
		self.assertEqual(res["backfill_days"], 3)

	def test_role_required(self):
		email = f"nr{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "NR", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		frappe.set_user(email)
		with self.assertRaises(frappe.PermissionError):
			api.get_config("x")

	def test_get_config_registers_device_and_lists_senders(self):
		self.f.rule(senders=self.f.sender)
		extra = "zzdtb\n\n" + self.f.sender.lower()
		frappe.db.set_single_value("SMS Payments Settings", "sms_extra_senders", extra)
		dev = "D" + frappe.generate_hash(length=8)
		res = api.get_config(dev, "Phone", "1.0")
		self.assertTrue(res["enabled"])
		self.assertEqual(res["device"], dev)
		self.assertEqual(res["backfill_days"], 3)
		self.assertIn("ZZDTB", res["watched_senders"])
		self.assertEqual(res["watched_senders"].count(self.f.sender), 1)
		self.assertEqual(res["watched_senders"], sorted(res["watched_senders"]))
		self.assertEqual(frappe.db.get_value("SMS Device", dev, "device_name"), "Phone")
		self.assertTrue(frappe.db.get_value("SMS Device", dev, "last_seen"))

	def test_get_config_disabled(self):
		frappe.db.set_single_value("SMS Payments Settings", "sms_enabled", 0)
		res = api.get_config("D" + frappe.generate_hash(length=8))
		self.assertFalse(res["enabled"])
		self.assertEqual(res["watched_senders"], [])

	def test_upload_idempotent(self):
		dev = device()
		m = self.msg()
		r1 = api.upload(dev, [m])["results"][0]
		r2 = api.upload(dev, [m])["results"][0]
		self.assertEqual((r1["status"], r2["status"]), ("accepted", "duplicate"))
		self.assertEqual(frappe.db.count("SMS Log", {"device": dev}), 1)

	def test_upload_marks_samples(self):
		dev = device()
		normal, sample = self.msg(), self.msg()
		api.upload(dev, [normal])
		api.upload(dev, [sample], sample="true")
		flags = [frappe.db.get_value("SMS Log", {"device": dev, "phone_sms_id": m["phone_sms_id"]}, "is_sample")
			for m in (normal, sample)]
		self.assertEqual(flags, [0, 1])

	def test_upload_json_string_and_int_id(self):
		import json
		dev = device()
		res = api.upload(dev, json.dumps([self.msg(phone_sms_id=12345)]))["results"][0]
		self.assertEqual(res["phone_sms_id"], "12345")
		self.assertEqual(res["status"], "accepted")

	def test_upload_rejects_bad_message_keeps_rest(self):
		dev = device()
		res = api.upload(dev, [self.msg(), {**self.msg(), "body": ""}])["results"]
		self.assertEqual([r["status"] for r in res], ["accepted", "rejected"])
		self.assertTrue(res[1]["error"])

	def test_upload_disabled_device(self):
		dev = device()
		frappe.db.set_value("SMS Device", dev, "enabled", 0)
		with self.assertRaises(frappe.PermissionError):
			api.upload(dev, [self.msg()])
		with self.assertRaises(frappe.PermissionError):
			api.upload("nope" + frappe.generate_hash(length=6), [self.msg()])

	def test_upload_over_100(self):
		with self.assertRaises(frappe.ValidationError):
			api.upload(device(), [self.msg() for _ in range(101)])

	def test_upload_sms_disabled(self):
		frappe.db.set_single_value("SMS Payments Settings", "sms_enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			api.upload(device(), [self.msg()])

	def test_received_at_ms_converted(self):
		dev = device()
		api.upload(dev, [self.msg()])
		got = frappe.db.get_value("SMS Log", {"device": dev}, "received_at")

		from frappe.utils import convert_utc_to_system_timezone, get_datetime
		exp = convert_utc_to_system_timezone(datetime.fromtimestamp(1_700_000_000, UTC)).replace(tzinfo=None)
		self.assertEqual(get_datetime(got), exp)

	def test_stats_shape(self):
		self.f.rule(auto_post=1)
		party_rule("Customer", make_customer("ST"), self.f.name)
		dev = device()
		now_ms = int(datetime.now(UTC).timestamp() * 1000)  # real instant; the API converts to system tz
		api.upload(dev, [self.msg(received_at_ms=now_ms)])
		api.upload(dev, [self.msg(body="nothing matches here", received_at_ms=now_ms)])
		s = api.stats(dev)
		self.assertEqual(len(s["daily"]), 14)
		self.assertEqual(s["daily"][-1]["date"], today())
		self.assertEqual(s["daily"][0]["date"], add_days(today(), -13))
		self.assertEqual(s["daily"][-1]["matched"], 1)
		self.assertEqual(s["daily"][-1]["unmatched"], 1)
		self.assertEqual(s["unmatched_total"], 1)
		self.assertEqual(len(s["events"]), 2)
		self.assertEqual(len(s["last_posted_at"]), 19)

	def test_upload_per_message_isolation(self):
		dev = device()
		long_sender = {**self.msg(), "sender": "X" * 300}
		res = api.upload(dev, [self.msg(), long_sender, "junk", {**self.msg(), "sim_slot": "abc"}])["results"]
		self.assertEqual([r["status"] for r in res], ["accepted", "rejected", "rejected", "accepted"])
		self.assertEqual(frappe.db.count("SMS Log", {"device": dev}), 2)

	def test_upload_transient_error_fails_request(self):
		with patch.object(api, "ingest", side_effect=frappe.QueryTimeoutError):
			with self.assertRaises(frappe.QueryTimeoutError):
				api.upload(device(), [self.msg()])

	def test_upload_validation_error_is_rejected(self):
		with patch.object(api, "ingest", side_effect=frappe.ValidationError("bad")):
			res = api.upload(device(), [self.msg()])["results"][0]
		self.assertEqual(res["status"], "rejected")

	def test_upload_long_body_rejected_and_sim_slot_bounded(self):
		dev = device()
		res = api.upload(dev, [self.msg(body="x" * 2001), self.msg(sim_slot=2**40)])["results"]
		self.assertEqual([r["status"] for r in res], ["rejected", "accepted"])
		self.assertEqual(frappe.db.get_value("SMS Log", {"device": dev}, "sim_slot"), 0)

	def test_upload_is_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[api.upload], ["POST"])

	def test_get_config_device_disabled(self):
		dev = device()
		frappe.db.set_value("SMS Device", dev, "enabled", 0)
		self.assertFalse(api.get_config(dev)["enabled"])

	def test_gateway_role_allowed(self):
		email = f"gw{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": "GW", "send_welcome_email": 0,
			"roles": [{"role": "SMS Gateway"}],
		}).insert(ignore_permissions=True)
		frappe.set_user(email)
		api._check_caller()

	def test_auto_post_from_gateway_user_upload(self):
		# The phone's API user has only SMS Gateway; the job it enqueues must still post the Payment Entry.
		self.f.rule(auto_post=1)
		party_rule("Customer", make_customer("GWAP"), self.f.name)
		dev = device()
		email = f"gwap{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": "GWAP", "send_welcome_email": 0,
			"roles": [{"role": "SMS Gateway"}],
		}).insert(ignore_permissions=True)
		frappe.set_user(email)
		res = api.upload(dev, [self.msg()])
		frappe.set_user("Administrator")
		self.assertEqual(res["results"][0]["status"], "accepted")
		entry = frappe.get_doc("SMS Payment Register", {"reference": self.f.ref})
		self.assertEqual(entry.docstatus, 1)
		self.assertTrue(entry.payment_entry)
		self.assertEqual(frappe.session.user, "Administrator")

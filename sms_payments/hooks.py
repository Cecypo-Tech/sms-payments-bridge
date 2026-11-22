app_name = "sms_payments"
app_title = "SMS Payments"
app_publisher = "Cecypo.Tech"
app_description = "Record M-Pesa and bank payments from SMS forwarded by the SMS Payments Bridge Android app"
app_email = "support@cecypo.tech"
app_license = "gpl-3.0"

required_apps = ["erpnext"]

after_install = "sms_payments.sms_payments.ensure_role"
after_migrate = ["sms_payments.sms_payments.ensure_role"]

# Hide stack traces in failed responses to the phone API.
after_request = ["sms_payments.utils.request_hooks.after_request"]

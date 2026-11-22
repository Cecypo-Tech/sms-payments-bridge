frappe.listview_settings["SMS Log"] = {
	get_indicator(doc) {
		const colour = { Matched: "green", Unmatched: "orange", Error: "red", Pending: "blue" }[doc.status] || "gray";
		return [__(doc.status), colour, "status,=," + doc.status];
	},

	onload(listview) {
		// checked rows if any, otherwise every Pending/Unmatched/Error log (chosen server-side)
		listview.page.add_inner_button(__("Reprocess Unmatched"), () => {
			const log_names = listview.get_checked_items(true);
			const run = () =>
				frappe.call({
					method: "sms_payments.sms_payments.pipeline.reprocess",
					args: { log_names },
					callback: (r) => {
						frappe.show_alert({ message: __("{0} queued", [r.message]), indicator: "green" });
						listview.refresh();
					},
				});
			if (log_names.length) run();
			else frappe.confirm(__("Reprocess every pending, unmatched and error SMS?"), run);
		});
	},

	// The list's own Add button calls this instead of opening a new form; the list re-applies its
	// primary action whenever row selection changes, so page.set_primary_action from onload would not stick.
	primary_action() {
		const d = new frappe.ui.Dialog({
			title: __("Add SMS manually"),
			fields: [
				{ fieldname: "sender", fieldtype: "Data", label: __("Sender"), reqd: 1 },
				{
					fieldname: "received_at",
					fieldtype: "Datetime",
					label: __("Received at"),
					default: frappe.datetime.now_datetime(),
					reqd: 1,
				},
				{ fieldname: "body", fieldtype: "Small Text", label: __("Message"), reqd: 1 },
			],
			primary_action_label: __("Add"),
			primary_action(values) {
				frappe.call({
					method: "sms_payments.sms_payments.api.add_manual_sms",
					args: values,
					callback: (r) => {
						d.hide();
						frappe.set_route("Form", "SMS Log", r.message);
					},
				});
			},
		});
		d.show();
	},
};

frappe.ui.form.on("SMS Log", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.status === "Unmatched") {
			frm.add_custom_button(__("Create Rule from this SMS"), () => {
				frappe.call({
					method: "sms_payments.sms_payments.suggest.make_rule_from_log",
					args: { log_name: frm.doc.name },
					callback: (r) => frappe.new_doc("SMS Rule", r.message),
				});
			});
		}
		frm.add_custom_button(__("Copy AI prompt"), () => {
			frappe.call({
				method: "sms_payments.sms_payments.suggest.ai_prompt",
				args: { senders: frm.doc.sender, log_name: frm.doc.name },
				callback: (r) => {
					frappe.utils.copy_to_clipboard(r.message);
					frappe.msgprint({
						title: __("Prompt copied"),
						message: (frm.doc.status === "Unmatched"
							? __("Paste it into any AI assistant (Claude, ChatGPT, Gemini). Then press Create Rule from this SMS and replace Pattern and Date Format (under Advanced) with the two lines of its answer.")
							: __("Paste it into any AI assistant (Claude, ChatGPT, Gemini). Put the two lines of its answer into the rule's Pattern and Date Format (under Advanced).")) + "<br><br>" + __("The prompt contains the text of this SMS and up to two others from the same sender."),
					});
				},
			});
		});
		if (["Pending", "Unmatched", "Error"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Reprocess"), () => {
				frappe.call({
					method: "sms_payments.sms_payments.pipeline.reprocess",
					args: { log_names: [frm.doc.name] },
					callback: () => {
						frappe.show_alert(__("Queued. Reload in a moment."));
						setTimeout(() => frm.reload_doc(), 3000);
					},
				});
			});
		}
	},
});

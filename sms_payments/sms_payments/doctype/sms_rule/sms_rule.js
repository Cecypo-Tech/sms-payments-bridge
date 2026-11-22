frappe.ui.form.on("SMS Rule", {
	refresh(frm) {
		frm.add_custom_button(__("Copy AI prompt"), () => {
			frappe.call({
				method: "sms_payments.sms_payments.suggest.ai_prompt",
				args: { senders: frm.doc.senders },
				callback: (r) => {
					if (!r.message) return frappe.msgprint(__("No SMS from these senders yet. Fill in Senders, or open an SMS Log and use Copy AI prompt there."));
					frappe.utils.copy_to_clipboard(r.message);
					frappe.msgprint({
						title: __("Prompt copied"),
						message: __("Paste it into any AI assistant (Claude, ChatGPT, Gemini). Put the PATTERN line of its answer into Pattern and the DATE FORMAT line into Date Format (under Advanced), then press Test on Recent SMS.") + "<br><br>" + __("The prompt contains the text of up to three SMS from these senders."),
					});
				},
			});
		});
		frm.add_custom_button(__("Test on Recent SMS"), () => {
			frappe.call({
				method: "sms_payments.sms_payments.suggest.test_rule",
				args: { rule: frm.doc },
				callback: (r) => {
					const rows = (r.message || []).map((x) => {
						const result = x.error
							? frappe.utils.escape_html(x.error)
							: x.matched
								? frappe.utils.escape_html(Object.entries(x.values).map(([k, v]) => k + ": " + v).join(", "))
								: "-";
						return `<tr><td>${x.matched ? "&#10003;" : "&#10007;"}</td>
							<td>${frappe.utils.escape_html(x.body)}</td><td>${result}</td></tr>`;
					});
					frappe.msgprint({
						title: __("Test against recent SMS"),
						wide: true,
						message: rows.length
							? `<table class="table table-bordered"><tr><th></th><th>${__("Message")}</th>
								<th>${__("Extracted")}</th></tr>${rows.join("")}</table>`
							: __("No SMS Logs from these senders."),
					});
				},
			});
		});
	},
});

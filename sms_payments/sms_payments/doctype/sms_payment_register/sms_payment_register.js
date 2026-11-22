frappe.ui.form.on("SMS Payment Register", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.set_intro(__("Submitting creates and submits a Payment Entry."), "blue");
		}
		const type = { Receive: "Customer", Pay: "Supplier" }[frm.doc.payment_type];
		if (frm.doc.docstatus !== 0 || frm.is_new() || frm.doc.sms_party_rule || !type) return;
		frm.add_custom_button(__("Create Party Rule"), () => {
			const by_name = !!frm.doc.party_name_in_sms;
			const d = new frappe.ui.Dialog({
				title: __("Create Party Rule"),
				fields: [
					{ fieldname: "match_on", fieldtype: "Data", label: __("Match On"), read_only: 1, default: by_name ? "Name" : "Phone" },
					{ fieldname: "match_type", fieldtype: "Data", label: __("Match Type"), read_only: 1, default: "Exact" },
					{ fieldname: "value", fieldtype: "Data", label: __("Name or phone in the SMS"), reqd: 1, default: by_name ? frm.doc.party_name_in_sms : frm.doc.party_phone },
					{ fieldname: "party_type", fieldtype: "Data", label: __("Party Type"), read_only: 1, default: type },
					{ fieldname: "party", fieldtype: "Link", label: __("Party"), options: type, reqd: 1, default: frm.doc.party },
				],
				primary_action_label: __("Save"),
				primary_action(v) {
					frappe.db.insert({ doctype: "SMS Party Rule", enabled: 1, ...v }).then(() => {
						d.hide();
						frm.reload_doc();
					});
				},
			});
			d.show();
		});
	},
});

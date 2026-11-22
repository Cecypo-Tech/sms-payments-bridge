frappe.listview_settings["SMS Payment Register"] = {
	add_fields: ["party", "payment_type"],
	has_indicator_for_draft: 1,
	get_indicator(doc) {
		if (doc.docstatus === 0) {
			if (!doc.party && doc.payment_type !== "Internal Transfer") {
				return [__("Needs Party"), "orange", "party,is,not set|docstatus,=,0"];
			}
			return [__("To Post"), "blue", "docstatus,=,0"];
		}
		if (doc.docstatus === 1) return [__("Posted"), "green", "docstatus,=,1"];
	},
};

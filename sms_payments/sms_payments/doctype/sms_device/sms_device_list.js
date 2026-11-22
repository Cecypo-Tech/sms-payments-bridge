frappe.listview_settings["SMS Device"] = {
	add_fields: ["enabled", "last_seen"],
	get_indicator(doc) {
		if (!doc.enabled) return [__("Disabled"), "gray", "enabled,=,0"];
		// last_seen is stored in system time
		if (!doc.last_seen || frappe.datetime.get_hour_diff(frappe.datetime.system_datetime(), doc.last_seen) >= 24) {
			return [__("Not seen"), "orange"];
		}
		return [__("Active"), "green"];
	},
};

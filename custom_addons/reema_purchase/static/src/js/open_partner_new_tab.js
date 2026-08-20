/** @odoo-module **/
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component } from "@odoo/owl";

// Opens the record's partner_id contact form in a new browser tab —
// deliberately pure client-side, NOT a type="object" button. An object
// button forces Odoo to save the current record first so the server method
// has a real res_id to run against; on a brand-new, never-saved Vendor Bill
// (e.g. right after picking a vendor with no GL account yet) that silently
// creates a phantom draft the moment this is clicked. Reading partner_id
// straight out of already-loaded record data avoids any server round trip
// for the current record entirely, so nothing is ever saved by clicking it.
export class OpenPartnerNewTabWidget extends Component {
    static template = "reema_purchase.OpenPartnerNewTab";
    static props = { ...standardWidgetProps };

    get partnerId() {
        const value = this.props.record.data.partner_id;
        return value && value[0];
    }

    onClick() {
        if (!this.partnerId) {
            return;
        }
        window.open(`/odoo/action-base.action_partner_form/${this.partnerId}`, "_blank");
    }
}

registry.category("view_widgets").add("reema_open_partner_new_tab", {
    component: OpenPartnerNewTabWidget,
});

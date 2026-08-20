/** @odoo-module **/

import { registry } from "@web/core/registry";
import { many2OneField, Many2OneField } from "@web/views/fields/many2one/many2one_field";

/**
 * Many2one field variant that opens the linked record in a new browser tab
 * instead of navigating away from the current form.
 * Usage: widget="reema_hr_many2one_new_tab"
 */
class ReemaHrMany2OneNewTabField extends Many2OneField {
    onClick(ev) {
        if (this.props.canOpen && this.props.readonly && this.resId) {
            ev.stopPropagation();
            ev.preventDefault();
            window.open(`/odoo/${this.urlRelation}/${this.resId}`, "_blank");
        }
    }
}

const reemaHrMany2OneNewTabField = {
    ...many2OneField,
    component: ReemaHrMany2OneNewTabField,
};

registry.category("fields").add("reema_hr_many2one_new_tab", reemaHrMany2OneNewTabField);

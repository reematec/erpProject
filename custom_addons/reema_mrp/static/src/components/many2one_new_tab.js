/** @odoo-module **/
import { registry } from "@web/core/registry";
import { many2OneField, Many2OneField } from "@web/views/fields/many2one/many2one_field";

/**
 * Many2one field variant that opens the linked record in a new browser tab
 * instead of navigating away from the current form.
 * Usage: widget="many2one_new_tab"
 */
class Many2OneNewTabField extends Many2OneField {
    onClick(ev) {
        if (this.props.canOpen && this.props.readonly && this.resId) {
            ev.stopPropagation();
            ev.preventDefault();
            window.open(`/odoo/${this.urlRelation}/${this.resId}`, "_blank");
        }
    }
}

const many2OneNewTabField = {
    ...many2OneField,
    component: Many2OneNewTabField,
};

registry.category("fields").add("many2one_new_tab", many2OneNewTabField);

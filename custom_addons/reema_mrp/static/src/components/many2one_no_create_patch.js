/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { many2OneField } from "@web/views/fields/many2one/many2one_field";

/**
 * Globally disable "Create", "Quick Create", and "Create and Edit" on every
 * Many2one field in the backend. Master data must be managed through their
 * own dedicated menus, not inline from dropdowns.
 */
patch(many2OneField, {
    extractProps(...args) {
        const props = super.extractProps(...args);
        return {
            ...props,
            canCreate: false,
            canQuickCreate: false,
            canCreateEdit: false,
        };
    },
});

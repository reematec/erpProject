/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";
import { registry } from "@web/core/registry";

// Block auto-save (urgentSave = F5/tab close) for unsaved reema.invoice records.
// urgentSave uses navigator.sendBeacon which fires even after page unload,
// so we stop it here before it reaches _save().
patch(Record.prototype, {
    async urgentSave() {
        if (this.resModel === "reema.invoice" && !this.resId) {
            return true;
        }
        return super.urgentSave(...arguments);
    },
});

// Block auto-save (beforeLeave = Odoo menu navigation) for unsaved reema.invoice records.
class ReemaInvoiceFormController extends FormController {
    async beforeLeave() {
        if (this.model.root.isNew) {
            return;
        }
        return super.beforeLeave(...arguments);
    }
}

registry.category("views").add("reema_invoice_form", {
    ...formView,
    Controller: ReemaInvoiceFormController,
});

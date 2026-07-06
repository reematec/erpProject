/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

const DISCARD_ON_LEAVE_MODELS = ["reema.gate.pass", "reema.grn", "reema.ilo.outward.pass"];

patch(FormController.prototype, {
    async beforeLeave() {
        const root = this.model.root;
        if (DISCARD_ON_LEAVE_MODELS.includes(root.resModel) && root.isNew) {
            await root.discard();
            return;
        }
        return super.beforeLeave(...arguments);
    },
});

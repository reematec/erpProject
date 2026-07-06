/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";
import { FormController } from "@web/views/form/form_controller";

// Globally prevent Odoo from silently auto-saving a *new* (unsaved) record when
// the user refreshes the page, closes the tab, or navigates to another menu.
// This stops half-filled New forms from being persisted as drafts (and from
// consuming sequence numbers). Existing records still auto-save as normal.

// urgentSave = F5 / tab close. It fires via navigator.sendBeacon even after the
// page starts unloading, so we short-circuit it before it reaches _save().
patch(Record.prototype, {
    async urgentSave() {
        // A record with no database id is new / unsaved -> discard, don't save.
        if (!this.resId) {
            return true;
        }
        return super.urgentSave(...arguments);
    },
});

// beforeLeave = navigating away via the Odoo menu / breadcrumbs. Skip the
// auto-save when the root record is new so it is discarded instead of persisted.
patch(FormController.prototype, {
    async beforeLeave() {
        if (this.model.root.isNew) {
            return;
        }
        return super.beforeLeave(...arguments);
    },
});

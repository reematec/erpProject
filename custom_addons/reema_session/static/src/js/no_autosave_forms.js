/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { Record } from "@web/model/relational_model/record";
import { FormController } from "@web/views/form/form_controller";
import { LeaveWithUnsavedChangesDialog } from "./leave_with_unsaved_changes_dialog";

// Globally stop Odoo from ever writing a record to the database except via
// an explicit Save click.
//
// New (never-saved) records: always discarded silently on every leave/hide/
// close path. Nothing external — like a sequence-based reference number —
// has ever been committed for them, so there's nothing worth prompting
// about; re-typing costs nothing.
//
// Existing records with real unsaved edits: never auto-saved silently.
//   - In-app navigation (breadcrumb/menu): a Save / Discard / Cancel dialog.
//   - Tab close / refresh: no custom dialog can be awaited from the native
//     beforeunload event, so we fall back to the browser's own "Leave
//     site?" prompt instead of writing anything.
//   - Tab switch / hide: left alone entirely — no save, no dialog. The SPA
//     keeps the edit in memory; nothing is lost by switching tabs.

patch(Record.prototype, {
    async urgentSave() {
        if (!this.resId) {
            // New/unsaved record: nothing worth keeping across a hard close.
            return true;
        }
        if (!this.dirty) {
            return true; // nothing to lose
        }
        // Existing record, real edits: never silently write (no sendBeacon,
        // no RPC attempted at all). Returning false makes core's own
        // beforeUnload() call ev.preventDefault(), producing the browser's
        // native Leave/Stay prompt — the only UI available at this point.
        // If the user leaves anyway, that's accepted data loss; nothing was
        // ever saved.
        return false;
    },
});

patch(FormController.prototype, {
    beforeVisibilityChange() {
        // Never silently save on tab-switch/hide, for new or existing
        // records — neutralize core's unconditional save() here entirely.
    },

    async beforeLeave() {
        const root = this.model.root;
        if (root.isNew) {
            return; // discard silently — no dialog, nothing was ever numbered
        }
        if (!root.dirty || this.allowLeavingWithoutSaving) {
            return; // nothing to lose, or an internal flow already granted leave
        }
        return new Promise((resolve) => {
            this.dialogService.add(LeaveWithUnsavedChangesDialog, {
                onSave: async () => {
                    const saved = await this.save({ onError: this.onSaveError.bind(this) });
                    resolve(saved); // false (validation failed) blocks navigation too
                },
                onDiscard: async () => {
                    await this.discard();
                    resolve(true);
                },
                onStay: () => resolve(false), // blocks navigation, form is untouched
            });
        });
    },
});

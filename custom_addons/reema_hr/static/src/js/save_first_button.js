/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ViewButton } from "@web/views/view_button/view_button";

/**
 * Opt-in patch: any button with class "o_reema_hr_save_first" is disabled
 * whenever its record is new or has unsaved edits, forcing an explicit Save
 * first. Odoo core always saves a dirty/new record before running any
 * type="object" button click — for a workflow-commit button (Confirm, Post,
 * Void, Reverse...) that's normally fine, but the user explicitly wants
 * these specific actions to require a real, separate Save click first,
 * never an implicit one bundled into the action.
 * Usage: add class="o_reema_hr_save_first" to the button in the arch.
 */
patch(ViewButton.prototype, {
    get disabled() {
        if (
            !super.disabled &&
            this.props.className?.split(" ").includes("o_reema_hr_save_first") &&
            this.props.record
        ) {
            return this.props.record.isNew || this.props.record.dirty;
        }
        return super.disabled;
    },
});

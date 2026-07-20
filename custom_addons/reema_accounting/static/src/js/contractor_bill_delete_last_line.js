/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { AccountMoveFormController } from "@account/components/account_move_form/account_move_form";

/**
 * On the Contractor Bill form, removing the last invoice line and clicking
 * Save is meant to delete the whole bill (an empty contractor bill has no
 * use). A normal save would succeed server-side but then the client tries to
 * re-fetch the now-deleted record and throws a "record not found" error.
 * Detour: call the same server action the "Delete Bill" button uses instead
 * of the normal save, so the client navigates away cleanly.
 *
 * Scoped to contractor bills only (batch_entry_ids is only ever populated
 * for those) so ordinary vendor bills/invoices keep their normal save.
 */
patch(AccountMoveFormController.prototype, {
    async save(params) {
        const record = this.model.root;
        const isContractorBill = (record.data.batch_entry_ids?.records?.length || 0) > 0;
        const hasNoLinesLeft = (record.data.invoice_line_ids?.records?.length || 0) === 0;

        if (isContractorBill && hasNoLinesLeft && record.data.state === "draft" && !record.isNew) {
            const action = await this.orm.call("account.move", "action_delete_contractor_bill", [
                [record.resId],
            ]);
            // Clear the pending local edits (the line removal we never sent
            // to the server) so the framework doesn't see a dirty record and
            // try its own save/reload of the now-deleted move before doAction
            // finishes navigating away.
            await record.discard();
            await this.actionService.doAction(action);
            return true;
        }
        return super.save(params);
    },
});

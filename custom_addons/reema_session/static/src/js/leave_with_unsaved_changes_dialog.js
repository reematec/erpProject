/** @odoo-module **/
import { Dialog } from "@web/core/dialog/dialog";
import { useChildRef } from "@web/core/utils/hooks";

import { Component } from "@odoo/owl";

// Odoo core's ConfirmationDialog only supports 2 buttons (confirm/cancel),
// not enough for Save / Discard / Cancel — this is a 3-button sibling of it,
// built the same way (thin Dialog wrapper, dismiss/backdrop = "stay here").
export class LeaveWithUnsavedChangesDialog extends Component {
    static template = "reema_session.LeaveWithUnsavedChangesDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onSave: Function,
        onDiscard: Function,
        onStay: Function,
    };

    setup() {
        this.modalRef = useChildRef();
        this.env.dialogData.dismiss = () => this._run(this.props.onStay);
        this.isProcessing = false;
    }

    onClickSave() {
        return this._run(this.props.onSave);
    }

    onClickDiscard() {
        return this._run(this.props.onDiscard);
    }

    onClickStay() {
        return this._run(this.props.onStay);
    }

    async _run(callback) {
        if (this.isProcessing) {
            return;
        }
        this.isProcessing = true;
        this.setButtonsDisabled(true);
        try {
            await callback();
        } finally {
            this.props.close();
        }
    }

    setButtonsDisabled(disabled) {
        if (!this.modalRef.el) {
            return;
        }
        for (const button of this.modalRef.el.querySelectorAll(".modal-footer button")) {
            button.disabled = disabled;
        }
    }
}

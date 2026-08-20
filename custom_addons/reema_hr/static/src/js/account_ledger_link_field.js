/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Renders a many2one field's value as a plain clickable link that opens the
 * linked account's ledger in a new tab via a direct RPC call — deliberately
 * NOT a type="object" button, since Odoo always saves the record first on
 * any object-button click, which would silently persist a still-unsaved
 * draft record just from clicking an informational link.
 * Usage: widget="reema_hr_account_ledger_link"
 */
class AccountLedgerLinkField extends Component {
    static template = "reema_hr.AccountLedgerLinkField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    get accountId() {
        return this.value ? this.value[0] : false;
    }

    get displayName() {
        return this.value ? this.value[1] : "";
    }

    async onClick() {
        if (!this.accountId) {
            return;
        }
        const action = await this.orm.call(
            "reema.hr.employee.advance",
            "action_open_account_ledger",
            [this.accountId]
        );
        this.actionService.doAction(action);
    }
}

registry.category("fields").add("reema_hr_account_ledger_link", {
    component: AccountLedgerLinkField,
});

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Many2ManyTagsFieldColorEditable } from "@web/views/fields/many2many_tags/many2many_tags_field";

// Vendor Bill's GRN/Gate Pass tags need to stay clickable (showing the real
// record, same rich detail as before) but genuinely non-editable for users
// without write access. Core's own "edit_tags" option can't be used here: it
// hardcodes activeActions.write = true regardless of the real ACL, so a
// read-only accountant still sees active Save/Discard buttons that would
// only fail once clicked. Opening the record's own form via a plain
// ir.actions.act_window instead lets core's normal access-rights check
// decide the mode correctly — no Save/Discard at all when write is denied.
const REEMA_READONLY_TAG_FIELDS = ["reema_grn_ids", "reema_gate_pass_ids"];

patch(Many2ManyTagsFieldColorEditable.prototype, {
    setup() {
        super.setup();
        if (
            this.props.record.resModel === "account.move" &&
            REEMA_READONLY_TAG_FIELDS.includes(this.props.name)
        ) {
            this.reemaActionService = useService("action");
        }
    },
    onTagClick(ev, record) {
        if (this.reemaActionService) {
            this.reemaActionService.doAction({
                type: "ir.actions.act_window",
                res_model: this.relation,
                res_id: record.resId,
                views: [[false, "form"]],
                target: "new",
            });
            return;
        }
        return super.onTagClick(ev, record);
    },
});

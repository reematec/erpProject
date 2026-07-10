/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    mrpWorkorderX2ManyField,
    MrpWorkorderX2ManyField,
} from "@mrp/views/fields/mrp_workorder_one2many";

/* Work Orders list on the MO form: clicking the "Balls Done" figure on any
   row opens that work order's log of batch entries — the Ball Receive Point
   (e.g. Stitching Center Receive) is a special case and opens the ILO Flow
   instead, since that figure nets out balls currently out for repair (see
   _compute_qty_balls_completed) and the ILO Flow is what explains a gap
   between it and Completed. Every other hall just gets its plain batch log
   (action_view_batch_log) — same click, same column, action picked per row.
   Other columns and rows keep their normal (read-only / inline-edit)
   behaviour.

   This tab is a one2many field widget (mrp_workorder_one2many), not a
   standalone list action — X2ManyField picks its Renderer from the FIELD
   widget's own `components.ListRenderer`, not from js_class on the nested
   arch. So the override has to happen at the field-widget level (below),
   not via a registry.category("views") entry. */
const NAV_COLUMNS = ["qty_balls_completed"];

function getNavAction(record, columnName) {
    if (!NAV_COLUMNS.includes(columnName)) {
        return null;
    }
    return record.data.is_ball_receive_point ? "action_view_ilo_flow" : "action_view_batch_log";
}

export class WorkorderCompletedNavRenderer extends MrpWorkorderX2ManyField.components.ListRenderer {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
    }

    getCellClass(column, record) {
        const classNames = super.getCellClass(column, record);
        if (getNavAction(record, column.name)) {
            return `${classNames} o_reema_wo_nav_cell`;
        }
        return classNames;
    }

    async onCellClicked(record, column, ev) {
        const model = this.props.list.model;
        // NOT this.isInlineEditable(record) — that only reports whether the LIST
        // as a whole allows inline edit (true for this list, always, regardless of
        // column), not whether THIS cell does. qty_balls_completed is readonly="1"
        // unconditionally, so it never enters inline-edit either way — gate on that
        // instead, via the actual per-cell check.
        const blockedByEdit =
            (model.multiEdit && record.selected) ||
            (this.editedRecord && this.editedRecord !== record);
        const navAction = getNavAction(record, column.name);
        if (
            !blockedByEdit &&
            !this.props.archInfo.noOpen &&
            !ev.target.special_click &&
            column.type === "field" &&
            navAction &&
            this.isCellReadonly(column, record)
        ) {
            const action = await this.orm.call(
                record.resModel,
                navAction,
                [[record.resId]]
            );
            if (action) {
                await this.action.doAction(action);
            }
            return;
        }
        return super.onCellClicked(record, column, ev);
    }
}

export class ReemaWorkorderCompletedNavX2ManyField extends MrpWorkorderX2ManyField {
    static components = {
        ...MrpWorkorderX2ManyField.components,
        ListRenderer: WorkorderCompletedNavRenderer,
    };
}

registry.category("fields").add("reema_workorder_completed_nav_one2many", {
    ...mrpWorkorderX2ManyField,
    component: ReemaWorkorderCompletedNavX2ManyField,
});

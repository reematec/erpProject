/** @odoo-module **/
import { registry } from "@web/core/registry";
import { AutoColumnWidthListRenderer } from "@stock/views/list/auto_column_width_list_renderer";
import { StockMoveX2ManyField, stockMoveX2ManyField } from "@stock/views/picking_form/stock_move_one2many";

/* Components are not lot/serial tracked and reservation is handled via the
   physical RMI issuance flow, so the core "Open Move" detail-operations
   column (added unconditionally by MovesListRenderer) is dead weight here. */
class ReemaMoveListRenderer extends AutoColumnWidthListRenderer {}

class ReemaMoveX2ManyField extends StockMoveX2ManyField {
    static components = { ...StockMoveX2ManyField.components, ListRenderer: ReemaMoveListRenderer };
}

registry.category("fields").add("reema_move_one2many", {
    ...stockMoveX2ManyField,
    component: ReemaMoveX2ManyField,
});

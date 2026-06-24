/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";

/* Product list: navigation is driven by specific figures, not by clicking
   anywhere on the row (which confused users into thinking the whole line was a
   single button):
     - Product Name  -> open the product form
     - On Hand       -> Moves History (same as the stock-move icon)
     - Forecasted    -> forecast report (Stock Ledger)
   Multi-edit / inline-edit behaviour is preserved untouched. */
const FIGURE_ACTIONS = {
    qty_available: "action_view_stock_move_lines",
    virtual_available: "action_product_tmpl_forecast_report",
};

class ProductNameNavRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
    }

    async onCellClicked(record, column, ev) {
        const model = this.props.list.model;
        const inEditFlow =
            (model.multiEdit && record.selected) ||
            this.isInlineEditable(record) ||
            (this.editedRecord && this.editedRecord !== record);
        if (inEditFlow) {
            // Preserve core multi-edit / inline-edit behaviour verbatim.
            return super.onCellClicked(record, column, ev);
        }
        if (this.props.archInfo.noOpen || ev.target.special_click || column.type !== "field") {
            return;
        }
        if (column.name === "name") {
            this.props.openRecord(record);
        } else if (column.name in FIGURE_ACTIONS) {
            await this._openFigureAction(record, FIGURE_ACTIONS[column.name]);
        }
    }

    async _openFigureAction(record, method) {
        const action = await this.orm.call(record.resModel, method, [[record.resId]], {
            context: { default_product_tmpl_id: record.resId },
        });
        if (action) {
            await this.action.doAction(action);
        }
    }
}

class ProductNameNavController extends ListController {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    get className() {
        return `${super.className || ""} o_reema_name_nav`;
    }

    /* Print whatever the list is currently showing: pass the live search domain
       (filters) and grouping to the HTML report, which renders the matching
       products (grouped into sections when grouped). */
    onPrintProducts() {
        const root = this.model.root;
        const params = new URLSearchParams();
        params.set("domain", JSON.stringify(root.domain || []));
        const groupBy = root.groupBy || [];
        if (groupBy.length) {
            params.set("groupby", groupBy.join(","));
        }
        this.actionService.doAction({
            type: "ir.actions.act_url",
            url: `/report/html/reema_mrp.report_products?${params.toString()}`,
            target: "new",
        });
    }
}

registry.category("views").add("product_name_nav_list", {
    ...listView,
    Controller: ProductNameNavController,
    Renderer: ProductNameNavRenderer,
    buttonTemplate: "reema_mrp.ProductsListButtons",
});

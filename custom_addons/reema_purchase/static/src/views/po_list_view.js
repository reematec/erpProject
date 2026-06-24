/** @odoo-module **/
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { registry } from "@web/core/registry";

/**
 * PO list view: keep the selection bar clean — when records are selected we
 * want only the selection count, no buttons. ActionMenus feeds both the
 * multi-record "Actions" cog (Export / Delete / Duplicate / …) and the "Print"
 * dropdown from its `action` / `print` item lists, and each dropdown only
 * renders when its list is non-empty. Returning empty lists hides both.
 */
class PoListController extends ListController {
    get actionMenuItems() {
        return { action: [], print: [] };
    }
}

registry.category("views").add("reema_po_list", {
    ...listView,
    Controller: PoListController,
});

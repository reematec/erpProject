/** @odoo-module **/
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";

class PendingBomListController extends ListController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    async openRecord(record) {
        const action = await this.orm.call(
            "reema.sampling.blueprint",
            "action_view_bom",
            [record.resId],
        );
        // orm.call returns the raw Python dict; doAction needs a `views` array
        // that the framework normally adds when loading actions by ID.
        if (action && action.view_mode && !action.views) {
            action.views = action.view_mode.split(",").map((v) => [false, v.trim()]);
        }
        this.actionService.doAction(action);
    }
}

const pendingBomListView = {
    ...listView,
    Controller: PendingBomListController,
};

registry.category("views").add("pending_bom_list", pendingBomListView);

/** @odoo-module **/
import { mrpWorkorderListView } from "@mrp/views/fields/mrp_workorder_one2many";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

class WorkorderStandaloneController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    }

    async openRecord(record) {
        const action = await this.orm.call(
            "mrp.workorder",
            "action_open_parent_mo",
            [[record.resId]]
        );
        await this.actionService.doAction(action);
    }
}

registry.category("views").add("reema_workorder_standalone_list", {
    ...mrpWorkorderListView,
    Controller: WorkorderStandaloneController,
});

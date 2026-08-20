/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";
import { DateTimeInput } from "@web/core/datetime/datetime_input";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

class AttendanceDateRangeListController extends ListController {
    static template = "reema_hr.AttendanceListView";
    static components = {
        ...ListController.components,
        DateTimeInput,
    };

    setup() {
        super.setup();
        this.dateRangeState = useState({ dateFrom: false, dateTo: false });
        this.dateFromGroupId = null;
        this.dateToGroupId = null;
    }

    onDateFromChange(value) {
        this.dateRangeState.dateFrom = value;
        this.applyDateBound("dateFromGroupId", "date", ">=", value);
    }

    onDateToChange(value) {
        this.dateRangeState.dateTo = value;
        this.applyDateBound("dateToGroupId", "date", "<=", value);
    }

    applyDateBound(groupIdKey, fieldName, operator, value) {
        const searchModel = this.env.searchModel;
        if (this[groupIdKey] !== null) {
            searchModel.deactivateGroup(this[groupIdKey]);
            this[groupIdKey] = null;
        }
        if (value) {
            const dateStr = value.toFormat("yyyy-MM-dd");
            const label = operator === ">=" ? "Date From" : "Date To";
            const groupId = searchModel.nextGroupId;
            searchModel.createNewFilters([
                {
                    description: `${label}: ${value.toFormat("MMM d, yyyy")}`,
                    domain: `[["${fieldName}", "${operator}", "${dateStr}"]]`,
                },
            ]);
            this[groupIdKey] = groupId;
        }
    }
}

registry.category("views").add("reema_hr_attendance_list", {
    ...listView,
    Controller: AttendanceDateRangeListController,
});

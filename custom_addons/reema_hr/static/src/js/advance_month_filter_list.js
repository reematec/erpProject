/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

// Mirrors MONTH_OPTIONS in payslip_month_filter_list.js — keep in sync.
const MONTH_OPTIONS = [
    ["1", "January"], ["2", "February"], ["3", "March"], ["4", "April"],
    ["5", "May"], ["6", "June"], ["7", "July"], ["8", "August"],
    ["9", "September"], ["10", "October"], ["11", "November"], ["12", "December"],
];

class AdvanceMonthFilterListController extends ListController {
    static template = "reema_hr.AdvanceListView";

    setup() {
        super.setup();
        this.monthOptions = MONTH_OPTIONS;
        this.filterState = useState({
            month: false,
            year: String(new Date().getFullYear()),
        });
        this.filterGroupId = null;
    }

    onMonthChange(ev) {
        this.filterState.month = ev.target.value || false;
        this.applyFilter();
    }

    onYearChange(ev) {
        this.filterState.year = ev.target.value;
        if (this.filterState.month) {
            this.applyFilter();
        }
    }

    applyFilter() {
        const searchModel = this.env.searchModel;
        if (this.filterGroupId !== null) {
            searchModel.deactivateGroup(this.filterGroupId);
            this.filterGroupId = null;
        }
        if (this.filterState.month) {
            const month = parseInt(this.filterState.month, 10);
            const year = parseInt(this.filterState.year, 10) || new Date().getFullYear();
            const label = this.monthOptions.find((m) => m[0] === this.filterState.month)[1];
            const dateFrom = `${year}-${String(month).padStart(2, "0")}-01`;
            const lastDay = new Date(year, month, 0).getDate();
            const dateTo = `${year}-${String(month).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;
            const groupId = searchModel.nextGroupId;
            searchModel.createNewFilters([
                {
                    description: `${label} ${year}`,
                    domain: `[["date", ">=", "${dateFrom}"], ["date", "<=", "${dateTo}"]]`,
                },
            ]);
            this.filterGroupId = groupId;
        }
    }
}

registry.category("views").add("reema_hr_advance_list", {
    ...listView,
    Controller: AdvanceMonthFilterListController,
});

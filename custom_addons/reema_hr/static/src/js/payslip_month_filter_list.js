/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

// Mirrors MONTH_SELECTION in reema_hr_payslip.py — keep in sync.
const MONTH_OPTIONS = [
    ["1", "January"], ["2", "February"], ["3", "March"], ["4", "April"],
    ["5", "May"], ["6", "June"], ["7", "July"], ["8", "August"],
    ["9", "September"], ["10", "October"], ["11", "November"], ["12", "December"],
];

class PayslipMonthFilterListController extends ListController {
    static template = "reema_hr.PayslipListView";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.monthOptions = MONTH_OPTIONS;
        this.filterState = useState({
            month: String(new Date().getMonth() + 1),
            year: String(new Date().getFullYear()),
        });
        // Purely cosmetic — keeps the Month/Year dropdowns showing the current
        // month, matching the "This Month" facet chip that's actually scoping
        // the list. The real scoping (never fetching every payslip ever
        // generated on open) is handled entirely by the "This Month" search
        // filter + the action's search_default_ context — that's evaluated by
        // the search model's own init, before the first fetch, which is the
        // only reliable place for it (calling searchModel methods here in
        // setup() races the model's own initial load and silently loses).
        // This widget only ever reacts to actual user input from here on.
    }

    // Replaces the arch's plain type="object" Print button (removed from the
    // list view's <header>) so we can read which columns are CURRENTLY
    // VISIBLE on screen and print exactly those — including columns a user
    // has toggled on/off via the list's own column picker. There's no public
    // API for "which optional columns are active" (that state lives in the
    // ListRenderer's own localStorage-backed bookkeeping, not exposed to the
    // controller), so instead we read it straight off the rendered DOM: every
    // visible field header <th> carries a data-name attribute (see
    // list_renderer.xml) — that's authoritative for "what's on screen right
    // now" regardless of how it got that way.
    async onClickPrint() {
        const selectedResIds = await this.model.root.getResIds(true);
        const printFields = [...this.rootRef.el.querySelectorAll("th[data-name]")].map(
            (th) => th.dataset.name
        );
        const action = await this.orm.call("reema.hr.payslip", "action_print_payslip", [selectedResIds], {
            context: {
                active_domain: this.props.domain,
                print_fields: printFields,
            },
        });
        if (action) {
            this.actionService.doAction(action);
        }
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
        // Wipe every active facet (the initial "No Month Selected" one, or
        // any previous month/other filter) rather than tracking a specific
        // group id — Month is the primary scope control here, so resetting
        // secondary facets (Draft/Confirmed, employee search, ...) on every
        // month change is the safer default vs. silently combining with a
        // stale facet and showing nothing.
        searchModel.clearQuery();
        if (this.filterState.month) {
            const label = this.monthOptions.find((m) => m[0] === this.filterState.month)[1];
            const year = parseInt(this.filterState.year, 10) || new Date().getFullYear();
            searchModel.createNewFilters([
                {
                    description: `${label} ${year}`,
                    domain: `[["period_month", "=", "${this.filterState.month}"], ["period_year", "=", ${year}]]`,
                },
            ]);
        } else {
            searchModel.createNewFilters([
                {
                    description: `Select a month to view payslips`,
                    domain: `[["id", "in", []]]`,
                },
            ]);
        }
    }
}

registry.category("views").add("reema_hr_payslip_list", {
    ...listView,
    Controller: PayslipMonthFilterListController,
});

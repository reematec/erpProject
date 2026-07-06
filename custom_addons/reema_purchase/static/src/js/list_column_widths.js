/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useEffect } from "@odoo/owl";

const PREFIX = "reema_col:";

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        // Wrap onStartResize to persist widths after each manual resize
        const orig = this.columnWidths.onStartResize;
        this.columnWidths.onStartResize = (ev) => {
            orig(ev);
            window.addEventListener(
                "pointerup",
                () => requestAnimationFrame(() => this._saveColWidths()),
                { once: true }
            );
        };

        // Runs after Odoo's own forceColumnWidths effect — restores saved widths
        useEffect(() => {
            this._loadColWidths();
        });
    },

    _colKey() {
        const model = this.props.list.resModel;
        const cols = (this.state?.columns || [])
            .map((c) => c.name || c.id || c.type)
            .join(",");
        return PREFIX + model + ":" + cols;
    },

    _saveColWidths() {
        const table = this.tableRef?.el;
        if (!table) return;
        const headers = [...table.querySelectorAll("thead th")];
        const widths = headers.map((th) => th.getBoundingClientRect().width);
        if (widths.some((w) => w > 0)) {
            localStorage.setItem(this._colKey(), JSON.stringify(widths));
        }
    },

    _loadColWidths() {
        const table = this.tableRef?.el;
        if (!table) return;
        let widths;
        try {
            const raw = localStorage.getItem(this._colKey());
            widths = raw ? JSON.parse(raw) : null;
        } catch (e) {
            return;
        }
        if (!widths) return;
        const headers = [...table.querySelectorAll("thead th")];
        if (headers.length !== widths.length) return;
        table.style.tableLayout = "fixed";
        headers.forEach((th, i) => {
            if (widths[i] > 0) th.style.width = `${widths[i]}px`;
        });
    },
});

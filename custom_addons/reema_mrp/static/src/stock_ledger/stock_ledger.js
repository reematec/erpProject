/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { formatFloat } from "@web/views/fields/formatters";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

export class ReemaStockLedger extends Component {
    static template = "reema_mrp.StockLedger";
    static components = { ControlPanel, Dropdown, DropdownItem };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.context = useState({ ...this.props.action.context });
        this.warehouses = useState([]);
        this.ledger = useState({
            loading: true,
            product_name: '',
            uom_name: '',
            on_hand: 0,
            opening_balance: 0,
            opening_date: '',
            closing_balance: 0,
            lines: [],
        });
        // null until the user picks a date; the backend then defaults it to the
        // earliest movement and returns the effective value.
        this.openingDate = null;

        onWillStart(async () => {
            const whs = await this.orm.searchRead(
                'stock.warehouse', [], ['id', 'name', 'code']
            );
            this.warehouses.push(...whs);
            if (!this.context.warehouse_id && this.warehouses.length) {
                this.context.warehouse_id = this.warehouses[0].id;
            }
            await this._loadData();
        });
    }

    async _loadData() {
        this.ledger.loading = true;
        const productId = this.context.active_id;
        const isTemplate = !this.context.active_model
            || this.context.active_model === 'product.template';
        const result = await this.orm.call(
            'reema.stock.ledger',
            'get_ledger_lines',
            [],
            {
                product_id: productId,
                is_template: isTemplate,
                warehouse_id: this.context.warehouse_id,
                opening_date: this.openingDate,
            }
        );
        this.ledger.product_name = result.product_name;
        this.ledger.uom_name = result.uom_name;
        this.ledger.on_hand = result.on_hand;
        this.ledger.opening_balance = result.opening_balance;
        this.ledger.opening_date = result.opening_date;
        this.ledger.closing_balance = result.closing_balance;
        this.ledger.lines = result.lines;
        // Keep the picker in sync with the effective opening date.
        this.openingDate = result.opening_date;
        this.ledger.loading = false;
    }

    async setWarehouse(id) {
        this.context.warehouse_id = id;
        await this._loadData();
    }

    async onOpeningDateChange(ev) {
        this.openingDate = ev.target.value || null;
        await this._loadData();
    }

    get activeWarehouseName() {
        const wh = this.warehouses.find(w => w.id === this.context.warehouse_id);
        return wh ? wh.name : '';
    }

    get warehouseItems() {
        return this.warehouses.map(wh => ({
            id: wh.id,
            label: wh.name,
            onSelected: () => this.setWarehouse(wh.id),
        }));
    }

    formatQty(val) {
        if (val === null || val === undefined) return '';
        return formatFloat(val, { digits: [false, 2] });
    }

    rowClass(ledgerState) {
        const map = {
            done: 'text-muted',
            reserved: 'table-info',
            partial: 'table-warning',
            demand: 'table-warning',
        };
        return map[ledgerState] || '';
    }
}

registry.category("actions").add("reema_stock_ledger", ReemaStockLedger);

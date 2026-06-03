/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

class BomOpsInfoBanner extends Component {
    static template = "reema_mrp.BomOpsInfoBanner";
    static props = ["*"];

    setup() {
        const key = "reema_bom_ops_banner";
        this.state = useState({ visible: localStorage.getItem(key) !== "hidden" });
        this._key = key;
    }

    hide() {
        this.state.visible = false;
        localStorage.setItem(this._key, "hidden");
    }

    show() {
        this.state.visible = true;
        localStorage.removeItem(this._key);
    }
}

registry.category("view_widgets").add("bom_ops_info_banner", { component: BomOpsInfoBanner });

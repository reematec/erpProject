/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

class MoConfirmBanner extends Component {
    static template = "reema_mrp.MoConfirmBanner";
    static props = ["*"];

    setup() {
        const key = "reema_mo_confirm_banner";
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

registry.category("view_widgets").add("mo_confirm_banner", { component: MoConfirmBanner });

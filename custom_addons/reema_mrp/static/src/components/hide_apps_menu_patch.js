/** @odoo-module **/
import { user } from "@web/core/user";
import { whenReady } from "@odoo/owl";

if (!user.isSystem) {
    whenReady(() => {
        document.body.classList.add("o_hide_apps_menu");
    });
}

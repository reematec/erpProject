/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { UserMenu } from "@web/webclient/user_menu/user_menu";

// Hides Documentation / Support / Onboarding / My Odoo.com account from the
// top-right user avatar menu — none of them are relevant on an on-premise,
// non-Odoo.com-hosted instance. Filtering here (at render time, after every
// module's registry.add() has already run) rather than removing the entries
// from the user_menuitems registry directly, since registry.remove() would
// race module load order (web_tour's "Onboarding" entry in particular is
// added lazily inside its service's start()).
// Note: these are the "id" field each item factory returns, not the registry
// key it's added under (web/webclient/user_menu/user_menu_items.js adds the
// "My Odoo.com account" item under registry key "odoo_account" but its own
// id field is "account" — getElements() below filters on the id field).
const HIDDEN_USER_MENU_IDS = new Set(["documentation", "support", "web_tour.tour_enabled", "account"]);

patch(UserMenu.prototype, {
    getElements() {
        return super.getElements().filter((element) => !HIDDEN_USER_MENU_IDS.has(element.id));
    },
});

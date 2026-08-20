/** @odoo-module **/
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";

// Chatter Layout (Technical > Chatter Layout) has no bulk actions (create="0"
// delete="0"), so the row-selector checkbox column is dead weight that only
// crowds out the "Bottom Chatter" checkbox next to it. Scoped to this one
// view via js_class so it doesn't touch selectors on any other list.
const reemaChatterLayoutListView = {
    ...listView,
    props(genericProps, view) {
        return {
            ...listView.props(genericProps, view),
            allowSelectors: false,
        };
    },
};

registry.category("views").add("reema_chatter_layout_list", reemaChatterLayoutListView);

/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { SIZES } from "@web/core/ui/ui_service";
import { useEffect, useRef } from "@odoo/owl";
import { FormController } from "@web/views/form/form_controller";
import { FormRenderer } from "@web/views/form/form_renderer";

// Models checked in Settings > Technical > Database Structure > Chatter
// Layout (ir.model.reema_bottom_chatter) always get a below-the-form
// chatter, at any window width.
//
// Real screen width alone decides this in THREE separate places that don't
// call each other, each holding its own `useService("ui")` reference:
//   - FormRenderer.uiService: mail's mailLayout() (aside vs bottom chatter)
//     and core form_compiler.js (row vs column for sheet + chatter).
//   - FormController.ui: className() toggles "o_xxl_form_view h-100", which
//     form_controller.scss ties to `.o_form_sheet_bg { overflow: auto }` —
//     the sheet's own independent scrollbar, on regardless of the
//     FormRenderer-level row/column fix above.
// Patching one leaves the others still reacting to the real viewport, so
// each service reference is wrapped separately, all clamped the same way.
const BOTTOM_CHATTER_MODELS = new Set(session.bottom_chatter_models || []);

function belowXxl(realUiService) {
    return new Proxy(realUiService, {
        get(target, prop, receiver) {
            if (prop === "size") {
                return Math.min(Reflect.get(target, prop, receiver), SIZES.XXL - 1);
            }
            return Reflect.get(target, prop, receiver);
        },
    });
}

// form_controller.scss caps .o_form_sheet_bg at a fixed max-width so it
// doesn't get absurdly wide next to an aside chatter. That cap is unrelated
// to row/column and stays in place once the chatter moves below, leaving a
// dead gutter where the chatter used to sit. This class (scoped to the
// forced-bottom models only, see bottom_chatter_models.scss) lifts it.
const FULL_WIDTH_SHEET_CLASS = "o_reema_full_width_sheet";

patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        if (!BOTTOM_CHATTER_MODELS.has(this.props.record.resModel)) {
            return;
        }
        this.uiService = belowXxl(this.uiService);

        const rootRef = useRef("compiled_view_root");
        useEffect(
            (el) => {
                if (!el) {
                    return;
                }
                el.classList.add(FULL_WIDTH_SHEET_CLASS);
                return () => el.classList.remove(FULL_WIDTH_SHEET_CLASS);
            },
            () => [rootRef.el]
        );
    },
});

patch(FormController.prototype, {
    setup() {
        super.setup();
        if (BOTTOM_CHATTER_MODELS.has(this.props.resModel)) {
            this.ui = belowXxl(this.ui);
        }
    },
});

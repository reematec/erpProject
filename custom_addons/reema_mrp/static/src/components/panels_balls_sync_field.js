import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";
import { useEffect } from "@odoo/owl";

class PanelsBallsSyncField extends FloatField {
    setup() {
        super.setup();
        // Attach a real-time input listener so the sibling field updates as the user types,
        // not only on blur (which is when Python @api.onchange fires).
        useEffect(
            (el) => {
                if (!el) return;
                const handler = (ev) => this._onPanelsBallsInput(ev);
                el.addEventListener("input", handler);
                return () => el.removeEventListener("input", handler);
            },
            () => [this.inputRef.el]
        );
    }

    _onPanelsBallsInput(ev) {
        const ppb = this.props.record.data.panels_per_ball;
        if (!ppb) return;
        // Use native parseFloat so in-progress input like "32." doesn't throw.
        const val = parseFloat(ev.target.value);
        if (isNaN(val)) return;
        if (this.props.name === "qty") {
            // Panels field → update balls
            this.props.record.update({ qty_balls_input: val / ppb });
        } else {
            // Balls field → update panels
            this.props.record.update({ qty: val * ppb });
        }
    }
}

registry.category("fields").add("panels_balls_sync", {
    ...floatField,
    component: PanelsBallsSyncField,
});

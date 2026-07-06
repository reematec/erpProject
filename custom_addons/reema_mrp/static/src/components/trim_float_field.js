import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";
import { MrpShouldConsumeOwl, mrpShouldConsumeOwl } from "@mrp/widgets/mrp_should_consume";
import { localization } from "@web/core/l10n/localization";

// Strip padding zeros (and a now-dangling decimal separator) from a formatted
// number string. Display-only: the stored value and all computations keep full
// precision; only what we render changes. Leaves non-strings (the raw-number
// branch of FloatField.formattedValue) untouched.
export function trimZeros(s) {
    const dp = localization.decimalPoint;
    if (typeof s === "string" && dp && s.includes(dp)) {
        s = s.replace(/0+$/, "");
        if (s.endsWith(dp)) {
            s = s.slice(0, -dp.length);
        }
    }
    return s;
}

// Plain Float field that hides padding zeros (e.g. 6.000000 -> 6,
// 0.031250 -> 0.03125). Editing is unchanged — only the display is trimmed.
export class TrimFloatField extends FloatField {
    get formattedValue() {
        return trimZeros(super.formattedValue);
    }
}

registry.category("fields").add("trim_float", {
    ...floatField,
    component: TrimFloatField,
});

// Same trimming for the MO "To Consume" column, which uses the standard
// mrp_should_consume widget (main qty + optional "should / total" prefix).
// We trim both the editable quantity and the should-consume prefix.
export class TrimMrpShouldConsume extends MrpShouldConsumeOwl {
    get formattedValue() {
        return trimZeros(super.formattedValue);
    }
    get shouldConsumeQty() {
        return trimZeros(super.shouldConsumeQty);
    }
}

registry.category("fields").add("trim_mrp_should_consume", {
    ...mrpShouldConsumeOwl,
    component: TrimMrpShouldConsume,
});

// Float field that shows "-" instead of "0.00" when the value is zero.
export class ZeroDashFloatField extends TrimFloatField {
    get formattedValue() {
        if (this.value === 0) return "-";
        return super.formattedValue;
    }
}

registry.category("fields").add("zero_dash_float", {
    ...floatField,
    component: ZeroDashFloatField,
});

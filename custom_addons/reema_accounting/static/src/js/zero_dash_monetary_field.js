import { registry } from "@web/core/registry";
import { MonetaryField, monetaryField } from "@web/views/fields/monetary/monetary_field";

// Same Monetary field, but shows "-" instead of "0.00" when the value is zero —
// e.g. the Journal Entries list Total column, mostly populated by non-invoice
// entries that have no total amount at all rather than a genuine zero.
export class ZeroDashMonetaryField extends MonetaryField {
    get formattedValue() {
        if (this.value === 0) return "-";
        return super.formattedValue;
    }
}

registry.category("fields").add("zero_dash_monetary", {
    ...monetaryField,
    component: ZeroDashMonetaryField,
});

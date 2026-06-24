import { registry } from "@web/core/registry";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";
import { trimZeros } from "./trim_float_field";

// Many2one for Piece Rate: search/select by name as usual, but display
// the numeric rate value (e.g. "12.5") in the cell once a rate is selected.
class PieceRateM2OField extends Many2OneField {
    get displayName() {
        const rate = this.props.record.data.piece_rate_value;
        if (this.value && rate !== undefined && rate !== null) {
            return trimZeros(rate.toFixed(2));
        }
        return super.displayName;
    }
}

registry.category("fields").add("piece_rate_m2o", {
    ...many2OneField,
    component: PieceRateM2OField,
});

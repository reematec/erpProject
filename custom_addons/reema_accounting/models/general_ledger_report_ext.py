from odoo import models


class GeneralLedgerReportExt(models.AbstractModel):
    _inherit = "report.account_financial_report.general_ledger"

    def _get_report_values(self, docids, data):
        res = super()._get_report_values(docids, data)
        # Reema only ever books in PKR — the "Rs." suffix on every single
        # amount cell is redundant and just eats column width. company_currency
        # drives the symbol via the monetary widget's display_currency option;
        # swap in an unsaved copy with an empty symbol instead of touching the
        # real PKR res.currency record, which other screens still rely on.
        currency = res.get("company_currency")
        if currency:
            res["company_currency"] = currency.new({
                "symbol": "",
                "position": currency.position,
                "decimal_places": currency.decimal_places,
                "rounding": currency.rounding,
            })
        return res

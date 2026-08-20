import json
from urllib.parse import quote

from odoo import models
from odoo.tools import json_default


class AccountFinancialReportAbstractWizardExt(models.AbstractModel):
    _inherit = 'account_financial_report_abstract_wizard'

    def button_export_html(self):
        # Core renders qweb-html reports as a client action with an <iframe>
        # inside the current tab (odoo/addons/web/.../report_action.js) —
        # replaces the whole screen the user was working from instead of
        # opening alongside it. Convert the standard report action into the
        # same html URL the iframe would have loaded (odoo/addons/web/.../
        # reports/utils.js:getReportUrl) and open that directly via
        # ir.actions.act_url, so every report under Accounting > Reporting
        # (General Ledger, Trial Balance, Journal Ledger, Open Items, Aged
        # Partner Balance, VAT Report — they all share this same abstract
        # wizard) opens as a genuine new browser tab instead. Was previously
        # only done for General Ledger specifically (general_ledger_wizard_ext.py);
        # moved up to the shared base so it applies to all of them at once.
        self.ensure_one()
        report_action = super().button_export_html()
        if not isinstance(report_action, dict) or report_action.get('type') != 'ir.actions.report':
            return report_action
        options = quote(json.dumps(report_action.get('data') or {}, default=json_default))
        context = quote(json.dumps(report_action.get('context') or {}, default=json_default))
        return {
            'type': 'ir.actions.act_url',
            'url': f"/report/html/{report_action['report_name']}?options={options}&context={context}",
            'target': 'new',
        }

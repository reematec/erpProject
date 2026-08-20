from odoo import fields, models


class GeneralLedgerReportWizardExt(models.TransientModel):
    _inherit = 'general.ledger.report.wizard'

    def _default_foreign_currency(self):
        # Reema only ever transacts in PKR — the OCA default (on whenever the
        # user has the Multi Currencies group, which most accounting users
        # here do) renders two "Amount cur." / "Cumul cur." columns that are
        # blank on every single row. Users who genuinely need it can still
        # tick the checkbox on the wizard themselves.
        return False

    def _default_show_cost_center(self):
        # No analytic accounting / cost centers in use — same reasoning as
        # foreign_currency above, this only ever renders an empty column.
        return False

    show_cost_center = fields.Boolean(default=_default_show_cost_center)

    # grouped_by='partners' (the OCA default) boxes every account into one
    # "ending balance" sub-block per partner — fine for an account with two
    # or three vendors, but the shared Contractors Payable account carries
    # dozens of contractors, so that's dozens of boxed subtotal rows before
    # you ever reach the real account total. 'none' renders every line
    # flat (still showing Partner as a normal column on each row) with a
    # single ending-balance footer per account instead.
    grouped_by = fields.Selection(default='none')

    # Opening reports as a new tab (instead of replacing the current screen)
    # is handled once for all six of these OCA wizards in
    # financial_report_wizard_ext.py, on the shared
    # account_financial_report_abstract_wizard base — General Ledger no
    # longer needs its own override of button_export_html.

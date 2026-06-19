from datetime import date

from odoo import models

TYPE_LABELS = {
    'asset_receivable':      'Receivable',
    'asset_cash':            'Bank & Cash',
    'asset_current':         'Current Asset',
    'asset_non_current':     'Non-current Asset',
    'asset_prepayments':     'Prepayments',
    'asset_fixed':           'Fixed Asset',
    'liability_payable':     'Payable',
    'liability_current':     'Current Liability',
    'liability_non_current': 'Non-current Liability',
    'equity':                'Equity',
    'equity_unaffected':     'Current Year Earnings',
    'income':                'Income',
    'income_other':          'Other Income',
    'expense':               'Expense',
    'expense_depreciation':  'Depreciation',
    'expense_direct_cost':   'Cost of Revenue',
    'off_balance':           'Off Balance',
}


class ReemaCOAReport(models.AbstractModel):
    _name = 'report.reema_accounting.report_coa'
    _description = 'Chart of Accounts Tree Report'

    def _get_report_values(self, docids, data=None):  # noqa: docids intentionally ignored — always renders full COA
        env = self.env
        groups_l1 = env['account.group'].search(
            [('parent_id', '=', False)],
            order='code_prefix_start',
        )
        all_accounts = env['account.account'].search([], order='code')
        accounts_by_group = {}
        for acc in all_accounts:
            key = acc.group_id.id if acc.group_id else 'ungrouped'
            accounts_by_group.setdefault(key, []).append(acc)

        return {
            'groups_l1': groups_l1,
            'accounts_by_group': accounts_by_group,
            'type_labels': TYPE_LABELS,
            'print_date': date.today().strftime('%d %B %Y'),
            'company': env.company,
        }

from odoo import _, fields, models
from odoo.exceptions import UserError


class ReemaLedgerWizardHr(models.TransientModel):
    """Extends reema_accounting's shared Ledger Wizard with an 'employee'
    type — employees aren't res.partner, so they need their own field and
    domain instead of reusing partner_id. See reema_ledger_wizard.py for the
    base 'nothing loads until you pick and click' design this follows."""
    _inherit = 'reema.ledger.wizard'

    ledger_type = fields.Selection(selection_add=[('employee', 'Employee')], ondelete={'employee': 'cascade'})
    employee_id = fields.Many2one('hr.employee', string='Employee', groups='hr.group_hr_user')

    def _get_ledger_domain(self):
        self.ensure_one()
        if self.ledger_type != 'employee':
            return super()._get_ledger_domain()
        if not self.employee_id:
            raise UserError(_('Select an employee first.'))
        account = self.employee_id.reema_advance_loan_account_id
        if not account:
            raise UserError(_('%s has no Advances & Loans account yet — none have been posted.') % self.employee_id.name)
        return [('account_id', '=', account.id)]

    def _get_ledger_party_name(self):
        self.ensure_one()
        if self.ledger_type == 'employee':
            return self.employee_id.name
        return super()._get_ledger_party_name()

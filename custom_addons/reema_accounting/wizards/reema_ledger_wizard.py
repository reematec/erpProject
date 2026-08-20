from odoo import _, fields, models
from odoo.exceptions import UserError


class ReemaLedgerWizard(models.TransientModel):
    """Picker in front of reema.ledger.line (reema_ledger_line.py) — nothing
    is queried until the user explicitly picks a partner (and optionally a
    date range) and clicks View Ledger. Deliberately not a plain "browse
    everything, grouped" list: that loads every posted line across every
    customer/vendor/contractor at once, which is both a lot of irrelevant
    data on screen and unnecessary DB/render load for a question that's
    almost always "what does THIS one party's account look like".

    One shared wizard for every ledger section (Customer/Vendor/Contractor
    here; reema_hr extends it with an 'employee' type) — only the partner
    domain and the resulting reema.ledger.line domain differ per type.
    """
    _name = 'reema.ledger.wizard'
    _description = 'Ledger Wizard'

    ledger_type = fields.Selection([
        ('customer', 'Customer'),
        ('vendor', 'Vendor'),
        ('contractor', 'Contractor'),
    ], required=True, default='customer')
    partner_id = fields.Many2one(
        'res.partner', string='Partner',
        domain="[('customer_rank', '>', 0)] if ledger_type == 'customer' "
               "else ([('supplier_rank', '>', 0), ('is_contractor', '=', False)] if ledger_type == 'vendor' "
               "else [('is_contractor', '=', True)])",
    )
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')

    def action_view_ledger(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise UserError(_('"From" date must not be after "To" date.'))
        domain = self._get_ledger_domain()
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ledger — %s') % (self._get_ledger_party_name(),),
            'res_model': 'reema.ledger.line',
            'view_mode': 'list',
            'views': [(self.env.ref('reema_accounting.view_reema_ledger_line_list').id, 'list')],
            'domain': domain,
            'target': 'current',
        }

    def _get_ledger_domain(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Select a partner first.'))
        return [('partner_id', '=', self.partner_id.id)]

    def _get_ledger_party_name(self):
        self.ensure_one()
        return self.partner_id.display_name

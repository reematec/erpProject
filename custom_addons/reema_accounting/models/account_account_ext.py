import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

REEMA_CODE_REGEX = re.compile(r'^[A-Za-z0-9.\-]+$')


class AccountGroupExt(models.Model):
    _inherit = 'account.group'
    _parent_name = 'parent_id'


class AccountAccountExt(models.Model):
    _inherit = 'account.account'

    group_id = fields.Many2one(
        'account.group',
        compute='_compute_account_group',
        store=True,
        search='_search_group_id',
        help="Account prefixes can determine account groups.",
    )

    target_group_id = fields.Many2one(
        'account.group',
        string='Account Group',
        store=False,
        domain="[('parent_id.parent_id', '!=', False)]",
        help="Select the Level 3 group. The account code will be auto-assigned.",
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        ondelete='set null',
        help="The partner this individual GL account belongs to.",
    )

    @api.constrains('code')
    def _check_account_code(self):
        for account in self:
            if account.code and not re.match(REEMA_CODE_REGEX, account.code):
                raise ValidationError(
                    "Account code may only contain alphanumeric characters, dots, and hyphens."
                )

    def _search_group_id(self, operator, value):
        if operator not in ('=', 'in'):
            return []
        ids = [value] if operator == '=' else value
        groups = self.env['account.group'].browse(ids)
        domain = []
        for group in groups:
            if group.code_prefix_start:
                domain += [('code', '=like', group.code_prefix_start + '-%')]
        return ['|'] * (len(domain) - 1) + domain if domain else [('id', '=', False)]

    @api.onchange('target_group_id')
    def _onchange_target_group_id(self):
        if not self.target_group_id:
            return
        prefix = self.target_group_id.code_prefix_start
        existing = self.env['account.account'].search(
            [('code', '=like', prefix + '-%')],
            order='code desc',
            limit=1,
        )
        if existing:
            seq = int(existing.code.rsplit('-', 1)[1])
            self.code = f'{prefix}-{seq + 1:02d}'
        else:
            self.code = f'{prefix}-01'

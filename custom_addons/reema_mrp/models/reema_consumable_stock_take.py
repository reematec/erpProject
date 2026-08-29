from datetime import datetime, time

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round, float_is_zero


class AccountMoveLineConsumableExt(models.Model):
    _inherit = 'account.move.line'

    # Set directly by the Consumable Stock Take confirm below, on Consumable
    # WIP (1-1-7-08) debit lines — there is no single reema.wo.batch.entry to
    # relate through the way reema_mo_id/reema_batch_entry_id (reema_wo_batch.py)
    # already do, since this value comes from a month-end stock count spread
    # across every order that ran at a hall during the period, not one
    # production event. Read back by _create_fg_conversion (reema_fg_costing.py)
    # to fold Consumable WIP into an MO's running WIP total the same way
    # Material and Labor WIP already are.
    reema_consumable_mo_id = fields.Many2one(
        'mrp.production', string='Consumable-Cost MO', readonly=True, copy=False,
    )


class ReemaConsumableStockTake(models.Model):
    _name = 'reema.consumable.stock.take'
    _description = 'Consumable Stock Take'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New', tracking=True)
    date = fields.Date(string='Count Date', required=True, default=fields.Date.context_today, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    line_ids = fields.One2many('reema.consumable.stock.take.line', 'stock_take_id', string='Lines')
    notes = fields.Text(string='Notes')
    total_consumed_value = fields.Float(
        string='Total Consumed Value', compute='_compute_total_consumed_value', digits=(10, 2),
    )

    @api.depends('line_ids.consumed_value')
    def _compute_total_consumed_value(self):
        for rec in self:
            rec.total_consumed_value = sum(rec.line_ids.mapped('consumed_value'))

    def unlink(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise UserError(_('Cancel "%s" before deleting it.') % rec.name)
        return super().unlink()

    def action_load_lines(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Lines can only be loaded on a draft stock take.'))
        Transaction = self.env['reema.consumable.transaction'].sudo()
        date_end = datetime.combine(self.date, time.max)
        txns = Transaction.search([('state', '=', 'done'), ('date', '<=', date_end)])
        pairs = {(t.location_id.id, t.product_id.id) for t in txns if t.location_id and t.product_id}
        existing_pairs = {(l.location_id.id, l.product_id.id) for l in self.line_ids}
        Line = self.env['reema.consumable.stock.take.line']
        created = 0
        for location_id, product_id in pairs:
            if (location_id, product_id) in existing_pairs:
                continue
            Line.create({
                'stock_take_id': self.id,
                'location_id': location_id,
                'product_id': product_id,
            })
            created += 1
        if not created:
            raise UserError(_('No new hall/consumable combinations found to load.'))

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only a draft stock take can be confirmed.'))
        if not self.line_ids:
            raise UserError(_('Add at least one line before confirming.'))
        if self.name == 'New':
            self.name = self.env['ir.sequence'].next_by_code('reema.consumable.stock.take') or 'New'
        for line in self.line_ids:
            line._reema_post_allocation()
        self.state = 'confirmed'
        self.message_post(body=_('Stock take confirmed — PKR %(amount).2f allocated.') % {
            'amount': self.total_consumed_value,
        })

    def action_cancel(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Only a confirmed stock take can be cancelled.'))
        for line in self.line_ids:
            line._reema_reverse_allocation()
        self.state = 'cancelled'
        self.message_post(body=_('Stock take cancelled — all allocation entries reversed.'))


class ReemaConsumableStockTakeLine(models.Model):
    _name = 'reema.consumable.stock.take.line'
    _description = 'Consumable Stock Take Line'
    _order = 'id'

    stock_take_id = fields.Many2one('reema.consumable.stock.take', required=True, ondelete='cascade')
    take_state = fields.Selection(related='stock_take_id.state', string='Status', store=True)
    take_date = fields.Date(
        related='stock_take_id.date', string='Count Date', store=True,
        help='Stored copy of the header date — needed so search(order=...) can '
             'sort/filter on it directly; Odoo does not support ordering by a '
             'dotted Many2one path here.',
    )
    location_id = fields.Many2one(
        'stock.location', string='Hall', required=True,
        domain="[('usage', '=', 'internal')]",
    )
    product_id = fields.Many2one(
        'product.product', string='Consumable', required=True,
        domain="[('categ_id.name', '=', 'Consumables')]",
    )
    product_uom_id = fields.Many2one('uom.uom', related='product_id.uom_id', string='UOM', readonly=True)

    window_start_date = fields.Date(
        string='Counting Since', readonly=True,
        help='Date of the previous confirmed stock take for this same hall/product — '
             'blank if this is the first count ever taken for this pair.',
    )
    opening_qty = fields.Float(string='Opening Qty', readonly=True)
    issued_qty = fields.Float(string='Issued', readonly=True)
    returned_qty = fields.Float(string='Returned', readonly=True)
    expected_qty = fields.Float(string='Expected Qty', readonly=True)
    counted_qty = fields.Float(string='Counted Qty')
    variance_qty = fields.Float(string='Variance', compute='_compute_variance', store=True)
    consumed_qty = fields.Float(string='Consumed Qty', compute='_compute_variance', store=True)
    unit_cost = fields.Float(string='Unit Cost', digits=(10, 2))
    consumed_value = fields.Float(string='Consumed Value', compute='_compute_variance', store=True, digits=(10, 2))
    account_move_id = fields.Many2one('account.move', string='Accounting Entry', readonly=True, copy=False)
    allocation_note = fields.Char(string='Allocation Note', readonly=True, copy=False)

    @api.depends('counted_qty', 'expected_qty', 'unit_cost')
    def _compute_variance(self):
        for line in self:
            line.variance_qty = line.counted_qty - line.expected_qty
            line.consumed_qty = line.expected_qty - line.counted_qty
            line.consumed_value = float_round(line.consumed_qty * line.unit_cost, precision_digits=2)

    @api.constrains('location_id', 'product_id', 'stock_take_id')
    def _check_unique(self):
        for line in self:
            siblings = line.stock_take_id.line_ids.filtered(
                lambda l: l.location_id == line.location_id and l.product_id == line.product_id and l.id != line.id
            )
            if siblings:
                raise UserError(_(
                    '"%(product)s" at "%(hall)s" is already on this stock take.'
                ) % {'product': line.product_id.name, 'hall': line.location_id.name})

    def _reema_find_previous_line(self):
        self.ensure_one()
        return self.search([
            ('location_id', '=', self.location_id.id),
            ('product_id', '=', self.product_id.id),
            ('take_state', '=', 'confirmed'),
            ('take_date', '<', self.stock_take_id.date),
            ('id', '!=', self.id),
        ], order='take_date desc, id desc', limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._reema_recompute_expected(seed_counted=True)
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('location_id', 'product_id')):
            self._reema_recompute_expected(seed_counted=True)
        return res

    def action_recompute_expected(self):
        self._reema_recompute_expected(seed_counted=False)

    def _reema_recompute_expected(self, seed_counted=False):
        Transaction = self.env['reema.consumable.transaction'].sudo()
        for line in self:
            if line.take_state != 'draft':
                continue
            if not line.location_id or not line.product_id:
                continue
            prev = line._reema_find_previous_line()
            opening = prev.counted_qty if prev else 0.0
            window_start = prev.stock_take_id.date if prev else False
            date_end = datetime.combine(line.stock_take_id.date, time.max)
            domain = [
                ('state', '=', 'done'),
                ('location_id', '=', line.location_id.id),
                ('product_id', '=', line.product_id.id),
                ('date', '<=', date_end),
            ]
            if window_start:
                domain.append(('date', '>', datetime.combine(window_start, time.max)))
            txns = Transaction.search(domain)
            issued = sum(txns.filtered(lambda t: t.transaction_type == 'issuance').mapped('qty'))
            returned = sum(txns.filtered(lambda t: t.transaction_type == 'return').mapped('qty'))
            expected = opening + issued - returned
            vals = {
                'window_start_date': window_start,
                'opening_qty': opening,
                'issued_qty': issued,
                'returned_qty': returned,
                'expected_qty': expected,
                'unit_cost': line.product_id.standard_price,
            }
            # Default the count to "nothing missing yet" so an unreviewed line
            # doesn't display its full expected qty as already-consumed —
            # never overwrites a count someone already typed in.
            if seed_counted and float_is_zero(line.counted_qty, precision_digits=2):
                vals['counted_qty'] = expected
            line.write(vals)

    def _reema_post_allocation(self):
        self.ensure_one()
        if float_is_zero(self.consumed_value, precision_digits=2):
            return False

        workcenters = self.env['mrp.workcenter'].search([('location_id', '=', self.location_id.id)])
        if not workcenters:
            self.allocation_note = _('Skipped — no work center configured at this hall location.')
            self.stock_take_id._message_log(body=_(
                'Consumable stock-take line skipped for %(product)s at %(hall)s — no '
                'work center found at that hall location. Value not allocated; needs '
                'manual review.'
            ) % {'product': self.product_id.name, 'hall': self.location_id.name})
            return False

        date_end = datetime.combine(self.stock_take_id.date, time.max)
        domain = [
            ('workorder_id.workcenter_id', 'in', workcenters.ids),
            ('date', '<=', date_end),
        ]
        if self.window_start_date:
            domain.append(('date', '>', datetime.combine(self.window_start_date, time.max)))
        batches = self.env['reema.wo.batch.entry'].sudo().search(domain)
        by_mo = {}
        for b in batches:
            if not b.mo_id:
                continue
            by_mo[b.mo_id] = by_mo.get(b.mo_id, 0.0) + b.qty_balls
        by_mo = {mo: qty for mo, qty in by_mo.items() if qty > 0}
        total_balls = sum(by_mo.values())

        if total_balls <= 0:
            self.allocation_note = _('Skipped — no production output at this hall during the period.')
            self.stock_take_id._message_log(body=_(
                'Consumable stock-take line skipped for %(product)s at %(hall)s — no '
                'order had output there during the counted period. Value of PKR '
                '%(amount).2f not allocated; needs manual review.'
            ) % {'product': self.product_id.name, 'hall': self.location_id.name, 'amount': self.consumed_value})
            return False

        Account = self.env['account.account'].sudo()
        hall_floor_acc = Account.search([('code', '=', '1-1-7-09')], limit=1)
        consumable_wip_acc = Account.search([('code', '=', '1-1-7-08')], limit=1)
        consumable_cogs_acc = Account.search([('code', '=', '5-1-1-02')], limit=1)
        if not (hall_floor_acc and consumable_wip_acc and consumable_cogs_acc):
            raise UserError(_('Missing Consumables — Hall Floor (1-1-7-09), Consumable WIP (1-1-7-08) '
                               'or Production Consumables Consumed (5-1-1-02) account.'))

        journal = self.env['account.journal'].sudo().search(
            [('code', '=', 'STK'), ('company_id', '=', self.env.company.id)], limit=1
        )
        if not journal:
            raise UserError(_('No STK journal configured.'))

        amount = self.consumed_value
        # Positive: value actually consumed -> Dr WIP/COGS, Cr Consumables — Hall Floor
        # (the value was already moved out of Consumables Stock at issuance time,
        # into the Hall Floor holding account — see reema_consumable_issuance.py).
        # Negative: physical count came in HIGHER than expected (e.g. a prior
        # miscount or an issuance that was never really used) -> mirror-reverse
        # the same split, same convention reema_wip_costing.py uses for returns.
        is_consumption = amount > 0
        label = f'Consumable Stock Take {self.stock_take_id.name} — {self.product_id.name} @ {self.location_id.name}'

        line_vals = []
        running = 0.0
        mo_items = list(by_mo.items())
        for i, (mo, balls) in enumerate(mo_items):
            if i == len(mo_items) - 1:
                share = float_round(abs(amount) - running, precision_digits=2)
            else:
                share = float_round(abs(amount) * (balls / total_balls), precision_digits=2)
                running += share
            if not share:
                continue
            already_packed = bool(mo.sudo().workorder_ids.filtered(
                lambda w: w.workcenter_id.is_packing).mapped('batch_entry_ids'))
            target_acc = consumable_cogs_acc if already_packed else consumable_wip_acc
            mo_label = f'{label} — {mo.name}'
            line_vals.append((0, 0, {
                'account_id': target_acc.id, 'name': mo_label,
                'debit': share if is_consumption else 0.0,
                'credit': 0.0 if is_consumption else share,
                'reema_consumable_mo_id': mo.id,
            }))

        if not line_vals:
            return False

        line_vals.append((0, 0, {
            'account_id': hall_floor_acc.id, 'name': label,
            'debit': 0.0 if is_consumption else abs(amount),
            'credit': abs(amount) if is_consumption else 0.0,
            'reema_hall_location_id': self.location_id.id,
        }))

        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.stock_take_id.date,
            'ref': label,
            'line_ids': line_vals,
        })
        move.sudo().action_post()
        self.account_move_id = move
        return move

    def _reema_reverse_allocation(self):
        self.ensure_one()
        if not self.account_move_id or self.account_move_id.state != 'posted':
            return False
        orig = self.account_move_id
        reversal_lines = [(0, 0, {
            'account_id': line.account_id.id, 'name': line.name,
            'debit': line.credit, 'credit': line.debit,
            'reema_consumable_mo_id': line.reema_consumable_mo_id.id,
        }) for line in orig.line_ids]
        reversal = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': orig.journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': f'Reversal: {orig.name}',
            'line_ids': reversal_lines,
        })
        reversal.sudo().action_post()
        return reversal

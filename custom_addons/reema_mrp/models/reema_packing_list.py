import math
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_round


class ReemaSamplingBlueprintWeight(models.Model):
    _inherit = 'reema.sampling.blueprint'

    weight_kg = fields.Float(
        string='Weight (kg)', compute='_compute_weight_kg',
        help='Parsed from Weight Range (e.g. "420 - 430 g") — average of the '
             'two numbers found, treated as grams. Used to auto-calculate '
             'Packing List Net Weight; there is no separate precise weight '
             'field to maintain.',
    )

    @api.depends('weight_range')
    def _compute_weight_kg(self):
        for rec in self:
            numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', rec.weight_range or '')][:2]
            rec.weight_kg = (sum(numbers) / len(numbers) / 1000.0) if numbers else 0.0


class AccountMoveCogsExt(models.Model):
    _inherit = 'account.move'

    # Marks the Dr COGS / Cr Finished Goods entries created when a Packing
    # List is confirmed — same identification purpose as is_fg_conversion
    # (reema_fg_costing.py), kept separate since these two move types are
    # never summed together for anything.
    is_packing_list_cogs = fields.Boolean(default=False, copy=False)


class ReemaWoBatchEntryPackingList(models.Model):
    _inherit = 'reema.wo.batch.entry'

    packing_claim_ids = fields.One2many(
        'reema.packing.list.line.batch', 'batch_entry_id', string='Packing Claims',
    )
    qty_shipped = fields.Float(
        string='Qty Shipped', compute='_compute_qty_shipped', store=True,
        help='Sum of quantity already claimed against this batch by Packing '
             'List article lines, across every non-cancelled Packing List — '
             'a batch can ship in more than one partial shipment over time.',
    )
    qty_remaining = fields.Float(
        string='Qty Remaining to Ship', compute='_compute_qty_shipped', store=True,
    )

    @api.depends('qty', 'packing_claim_ids.qty', 'packing_claim_ids.line_id.packing_list_id.state',
                 'box_packing_claim_ids.qty', 'box_packing_claim_ids.article_id.box_packing_id.state')
    def _compute_qty_shipped(self):
        # Nets out claims from both the existing Packing List and the newer
        # Box Packing List — they draw from the same batches, so a batch
        # claimed by one must show as unavailable to the other. See
        # box_packing_claim_ids on this model (reema_box_packing_list.py).
        for rec in self:
            old_shipped = sum(rec.packing_claim_ids.filtered(
                lambda c: c.line_id.packing_list_id.state != 'cancelled'
            ).mapped('qty'))
            new_shipped = sum(rec.box_packing_claim_ids.filtered(
                lambda c: c.article_id.box_packing_id.state != 'cancelled'
            ).mapped('qty'))
            shipped = old_shipped + new_shipped
            rec.qty_shipped = shipped
            rec.qty_remaining = rec.qty - shipped

    def _reema_fg_value(self, qty):
        """This batch's Finished Goods value for a qty slice of it — shared
        by the claim model's own fg_amount and the line's live onchange
        preview, so the proration formula only lives in one place."""
        self.ensure_one()
        move = self.fg_account_move_id
        if not move or not self.qty:
            return 0.0
        fg_acc = self.env['account.account'].sudo().search([('code', '=', '1-1-7-04')], limit=1)
        if not fg_acc:
            return 0.0
        total_fg = sum(
            move.sudo().line_ids.filtered(lambda l: l.account_id.id == fg_acc.id).mapped('debit')
        )
        return float_round(total_fg * (qty / self.qty), precision_digits=2)


class ReemaPackingList(models.Model):
    _name = 'reema.packing.list'
    _description = 'Packing List — Finished Goods to COGS'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, tracking=True,
        domain=[('customer_rank', '>', 0)],
        help='A Packing List always belongs to one client — it can bundle '
             'several of that client\'s orders, but never more than one client.',
    )
    client_address = fields.Text(string='Client Address')
    container_no = fields.Char(string='Container Number')
    commercial_invoice_no = fields.Char(
        string='Commercial Invoice No.', tracking=True,
        help='Cross-reference to the Commercial Invoice covering this '
             'shipment — links this Packing List and its Pro Forma '
             'Invoice(s) together under one shipment reference.',
    )
    total_cartons = fields.Integer(
        string='Total Cartons', compute='_compute_total_cartons', store=True,
    )
    net_weight = fields.Float(
        string='Net Weight (kg)', digits=(10, 2), compute='_compute_weights', store=True,
        help='Sum of each article line\'s qty × its product\'s own weight.',
    )
    gross_weight = fields.Float(
        string='Gross Weight (kg)', digits=(10, 2), compute='_compute_weights', store=True,
        help='Net Weight + each line\'s own (Cartons × Carton Weight) — '
             'different articles can use different carton sizes/weights.',
    )
    line_ids = fields.One2many('reema.packing.list.line', 'packing_list_id', string='Articles')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    account_move_id = fields.Many2one('account.move', string='COGS Entry', readonly=True, copy=False)
    total_amount = fields.Float(
        string='Total COGS', compute='_compute_total_amount', digits=(10, 2),
    )

    @api.depends('line_ids.fg_amount')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('fg_amount'))

    @api.depends('line_ids.carton_qty')
    def _compute_total_cartons(self):
        for rec in self:
            rec.total_cartons = sum(rec.line_ids.mapped('carton_qty'))

    @api.depends('line_ids.qty', 'line_ids.sample_id.weight_kg',
                 'line_ids.carton_qty', 'line_ids.carton_weight')
    def _compute_weights(self):
        for rec in self:
            net = sum(line.qty * line.sample_id.weight_kg for line in rec.line_ids)
            packaging = sum(line.carton_qty * line.carton_weight for line in rec.line_ids)
            rec.net_weight = net
            rec.gross_weight = net + packaging

    def _reema_sync_commercial_invoice_no(self, invoices=None):
        """Push this Packing List's Commercial Invoice No. onto the Pro
        Forma Invoice(s) it actually ships (via its lines' own invoice_id).
        One Commercial Invoice covers one physical shipment, so its number
        belongs on every order that shipment includes — auto-filled here
        instead of relying on someone typing it correctly twice."""
        for rec in self:
            if not rec.commercial_invoice_no:
                continue
            targets = invoices if invoices is not None else rec.line_ids.mapped('invoice_id')
            stale = targets.filtered(lambda inv: inv.commercial_invoice_no != rec.commercial_invoice_no)
            if stale:
                stale.write({'commercial_invoice_no': rec.commercial_invoice_no})

    @api.onchange('partner_id')
    def _onchange_partner_id_address(self):
        if self.partner_id:
            self.client_address = self.partner_id._display_address()

    def copy(self, default=None):
        # Blocked outright, not just hidden from the UI (duplicate="false"
        # on the views) — a duplicated Packing List would copy article lines
        # that immediately re-claim already-shipped batch quantity, corrupting
        # qty_remaining and COGS for every batch involved. Start a fresh
        # Packing List instead.
        raise UserError(_(
            'Packing Lists can\'t be duplicated — start a new one instead.'
        ))

    @api.model_create_multi
    def create(self, vals_list):
        # Reference number is assigned at Confirm, not here — a draft's
        # number would be a real, official shipment document reference
        # nothing has actually shipped against yet. See action_confirm().
        records = super().create(vals_list)
        records._reema_sync_commercial_invoice_no()
        return records

    def write(self, vals):
        if 'commercial_invoice_no' in vals and any(rec.state != 'confirmed' for rec in self):
            raise UserError(_(
                'Commercial Invoice No. can only be set once the Packing List is Confirmed.'
            ))
        res = super().write(vals)
        if 'commercial_invoice_no' in vals:
            self._reema_sync_commercial_invoice_no()
        return res

    def unlink(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise UserError(_('Cancel "%s" before deleting it.') % rec.name)
        return super().unlink()

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only a draft Packing List can be confirmed.'))
        if not self.line_ids:
            raise UserError(_('Add at least one article before confirming.'))

        # sudo: confirming a Packing List needs to read the batches' own
        # Accounting entries regardless of the confirming user's direct
        # Manufacturing/Accounting access — same reasoning as elsewhere in
        # this file (batches stay invisible to whoever is packing/shipping).
        Account = self.env['account.account'].sudo()
        fg_acc = Account.search([('code', '=', '1-1-7-04')], limit=1)
        material_cogs_acc = Account.search([('code', '=', '5-1-1-01')], limit=1)
        consumable_cogs_acc = Account.search([('code', '=', '5-1-1-02')], limit=1)
        if not (fg_acc and material_cogs_acc and consumable_cogs_acc):
            raise UserError(_('Missing Finished Goods (1-1-7-04), Raw Material Consumed (5-1-1-01) '
                               'or Production Consumables Consumed (5-1-1-02) account.'))

        if self.name == 'New':
            self.name = self.env['ir.sequence'].next_by_code('reema.packing.list') or 'New'

        claims = self.line_ids.mapped('batch_claim_ids')
        if not claims:
            raise UserError(_('Nothing to post — no article on this Packing List has a quantity allocated.'))

        line_vals = []
        for claim in claims:
            entry = claim.batch_entry_id.sudo()
            article = claim.line_id.pi_line_id
            fg_move = entry.fg_account_move_id
            if not fg_move or fg_move.state != 'posted':
                raise UserError(_(
                    'Batch "%s" has not been converted to Finished Goods yet — '
                    'cannot include it on a Packing List.'
                ) % entry.name)
            if not entry.reema_po_id or entry.reema_po_id.partner_id != self.partner_id:
                raise UserError(_(
                    'Batch "%(batch)s" belongs to a different client than this '
                    'Packing List (%(client)s).'
                ) % {'batch': entry.name, 'client': self.partner_id.name})
            if not entry.qty:
                continue
            fraction = claim.qty / entry.qty

            fg_line = fg_move.line_ids.filtered(lambda l: l.account_id.id == fg_acc.id)
            material_line = fg_move.line_ids.filtered(lambda l: l.account_id.code == '1-1-7-03')
            consumable_line = fg_move.line_ids.filtered(lambda l: l.account_id.code == '1-1-7-08')
            labor_lines = fg_move.line_ids.filtered(lambda l: l.account_id.code == '1-1-7-07')
            fg_amount = float_round(sum(fg_line.mapped('debit')) * fraction, precision_digits=2)
            if not fg_amount:
                continue

            label = f'Packing List {self.name} — {article.description or article.sample_name or article.sample_id.name or entry.name}'
            line_vals.append((0, 0, {
                'account_id': fg_acc.id, 'name': label,
                'debit': 0.0, 'credit': fg_amount,
                'reema_batch_entry_id': entry.id,
            }))
            material_amount = float_round(sum(material_line.mapped('credit')) * fraction, precision_digits=2)
            if material_amount:
                line_vals.append((0, 0, {
                    'account_id': material_cogs_acc.id, 'name': label,
                    'debit': material_amount, 'credit': 0.0,
                    'reema_batch_entry_id': entry.id,
                }))
            consumable_amount = float_round(sum(consumable_line.mapped('credit')) * fraction, precision_digits=2)
            if consumable_amount:
                line_vals.append((0, 0, {
                    'account_id': consumable_cogs_acc.id, 'name': label,
                    'debit': consumable_amount, 'credit': 0.0,
                    'reema_batch_entry_id': entry.id,
                }))
            for labor_line in labor_lines:
                labor_amount = float_round(labor_line.credit * fraction, precision_digits=2)
                if not labor_amount:
                    continue
                hall = labor_line.reema_source_workcenter_id
                if not hall or not hall.expense_account_id:
                    raise UserError(_(
                        'Hall "%s" has no Labor Expense Account configured — '
                        'set one on the work center before confirming this '
                        'Packing List.'
                    ) % (hall.name if hall else _('Unknown')))
                line_vals.append((0, 0, {
                    'account_id': hall.expense_account_id.id,
                    'name': f'{label} — {hall.name}',
                    'debit': labor_amount, 'credit': 0.0,
                    'reema_batch_entry_id': entry.id,
                    'reema_source_workcenter_id': hall.id,
                }))

        if not line_vals:
            raise UserError(_('Nothing to post — every article on this Packing List has zero value.'))

        journal = self.env['account.journal'].sudo().search(
            [('code', '=', 'STK'), ('company_id', '=', self.env.company.id)], limit=1
        )
        if not journal:
            raise UserError(_('No STK journal configured.'))

        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'is_packing_list_cogs': True,
            'line_ids': line_vals,
        })
        move.sudo().action_post()
        self.account_move_id = move
        self.state = 'confirmed'
        self.message_post(body=_(
            'Packing List confirmed — %(amount).2f moved from Finished Goods to COGS (entry %(move)s).'
        ) % {'amount': self.total_amount, 'move': move.name})

    def action_cancel(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Only a confirmed Packing List can be cancelled.'))
        if self.account_move_id and self.account_move_id.sudo().state == 'posted':
            orig = self.account_move_id.sudo()
            reversal_lines = [(0, 0, {
                'account_id': line.account_id.id, 'name': line.name,
                'debit': line.credit, 'credit': line.debit,
                'reema_batch_entry_id': line.reema_batch_entry_id.id,
                'reema_source_workcenter_id': line.reema_source_workcenter_id.id,
            }) for line in orig.line_ids]
            reversal = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': orig.journal_id.id,
                'date': fields.Date.context_today(self),
                'ref': f'Reversal: {orig.name}',
                'is_packing_list_cogs': True,
                'line_ids': reversal_lines,
            })
            reversal.sudo().action_post()
        self.state = 'cancelled'
        self.message_post(body=_('Packing List cancelled — COGS entry reversed.'))

    def action_print_packing_list(self):
        if not self:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_mrp.report_packing_list/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }


class ReemaPackingListLine(models.Model):
    _name = 'reema.packing.list.line'
    _description = 'Packing List Article Line'
    _order = 'packing_list_id, sequence, id'

    packing_list_id = fields.Many2one('reema.packing.list', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)

    # Order first, article second — picking the order narrows the Article
    # dropdown to that order's own lines, and stays its own report-groupable
    # column (each order printed as its own block, per the real document).
    invoice_id = fields.Many2one(
        'reema.invoice', string='Order', required=True,
        domain="[('partner_id', '=', parent.partner_id)]",
        options="{'no_open': True, 'no_create': True, 'no_edit': True}",
    )

    # The ordered article — a specific PI line, always scoped to one specific
    # order (never pooled with a client's other orders, even for the exact
    # same product): traceability/payment-processing requirement.
    pi_line_id = fields.Many2one(
        'reema.invoice.line', string='Article', required=True,
        help='The ordered article being shipped. Quantity, description, '
             'size and other details below come straight from this order line.',
    )
    product_id = fields.Many2one(
        'product.product', string='Product',
        compute='_compute_product_id', store=True, readonly=True,
    )
    available_qty = fields.Float(
        string='Ready to Ship', compute='_compute_available_qty',
        help='Produced and Finished-Goods-converted quantity still available '
             'for this specific article/order — never pooled with another '
             'order for the same client.',
    )
    qty = fields.Float(string='Qty')
    fg_amount = fields.Float(
        string='FG Value', digits=(10, 2), readonly=True,
        help='Live preview until saved (from the current allocation across '
             'available batches); the real, final value is fixed once the '
             'line is saved and its batch allocation is locked in.',
    )
    batch_claim_ids = fields.One2many(
        'reema.packing.list.line.batch', 'line_id', string='Batch Allocation', readonly=True,
        help='Which underlying production batch(es) this shipped quantity is '
             'actually drawn from — allocated automatically (oldest-produced '
             'first); not meant to be picked by hand.',
    )

    # Carton breakdown — matches the real Packing List document's own
    # columns, per article (different articles can use different carton
    # sizes/weights). Flow: qty is set first (validated against Ready to
    # Ship), then carton_size/qty_per_carton are entered, and carton_qty is
    # suggested from them (still freely editable afterward).
    carton_size = fields.Char(string='Carton Size', help='e.g. "40x30x30 cm"')
    carton_weight = fields.Float(string='Carton Weight (kg)', digits=(10, 2), help='Empty-carton weight.')
    qty_per_carton = fields.Float(string='Qty/Carton')
    carton_qty = fields.Integer(string='Cartons')
    carton_range = fields.Char(
        string='Carton No.', compute='_compute_carton_range',
        help='Auto-numbered from Cartons — each article\'s own cartons are '
             'numbered from 01, e.g. "01-04" for 4 cartons.',
    )
    carton_last_qty = fields.Float(
        string='Last Carton Qty', compute='_compute_carton_last_qty',
        help='How many units actually go in the last carton — if it\'s less '
             'than Qty/Carton, that carton has empty space.',
    )

    # Descriptive fields — sourced from the actual order line (pi_line_id),
    # not the generic product sample, since size/HS code/etc. are agreed
    # per order and can differ from the sample defaults. Freely editable
    # after the initial fill.
    sample_id = fields.Many2one(related='pi_line_id.sample_id', string='Sample', readonly=True)
    sample_code = fields.Char(string='Sample Code', compute='_compute_pi_fields', store=True, readonly=False)
    description = fields.Char(string='Description', compute='_compute_pi_fields', store=True, readonly=False)
    sample_color = fields.Char(string='Color', compute='_compute_pi_fields', store=True, readonly=False)
    hs_code = fields.Char(string='HS Code', compute='_compute_pi_fields', store=True, readonly=False)
    ean = fields.Char(string='EAN', compute='_compute_pi_fields', store=True, readonly=False)
    client_sku = fields.Char(string='Client SKU', compute='_compute_pi_fields', store=True, readonly=False)
    size = fields.Char(string='Size', compute='_compute_pi_fields', store=True, readonly=False)

    def _reema_source_po_lines(self):
        # sudo: batches/work orders/MOs are deliberately invisible to whoever
        # is building a Packing List (see class docstring on the batch model)
        # — they shouldn't need direct Manufacturing access just for this
        # lookup to resolve behind the scenes.
        self.ensure_one()
        if not self.pi_line_id:
            return self.env['reema.production.order.line']
        return self.env['reema.production.order.line'].sudo().search([
            ('invoice_line_id', '=', self.pi_line_id.id),
        ])

    def _reema_eligible_batches(self):
        self.ensure_one()
        mo_ids = self._reema_source_po_lines().mapped('mo_id').ids
        if not mo_ids:
            return self.env['reema.wo.batch.entry']
        return self.env['reema.wo.batch.entry'].sudo().search([
            ('mo_id', 'in', mo_ids),
            ('workorder_id.workcenter_id.is_packing', '=', True),
            ('fg_account_move_id', '!=', False),
        ], order='date asc')

    @api.depends('pi_line_id')
    def _compute_product_id(self):
        for line in self:
            po_lines = line._reema_source_po_lines()
            line.product_id = po_lines[:1].mo_id.product_id

    @api.depends('pi_line_id', 'batch_claim_ids.qty')
    def _compute_available_qty(self):
        for line in self:
            if not line.pi_line_id:
                line.available_qty = 0.0
                continue
            batches = line._reema_eligible_batches()
            own_claimed = sum(line.batch_claim_ids.mapped('qty'))
            line.available_qty = sum(batches.mapped('qty_remaining')) + own_claimed

    @api.depends('pi_line_id')
    def _compute_pi_fields(self):
        for line in self:
            article = line.pi_line_id
            line.sample_code = article.sample_code or False
            line.description = article.description or article.sample_name or article.sample_id.name or False
            line.sample_color = article.sample_color or False
            line.hs_code = article.hs_code or False
            line.ean = article.ean or False
            line.client_sku = article.client_sku or False
            line.size = article.size or False

    @api.depends('carton_qty', 'qty_per_carton', 'qty')
    def _compute_carton_last_qty(self):
        for line in self:
            if line.carton_qty > 0 and line.qty_per_carton > 0:
                line.carton_last_qty = line.qty - (line.carton_qty - 1) * line.qty_per_carton
            else:
                line.carton_last_qty = 0.0

    @api.depends('carton_qty')
    def _compute_carton_range(self):
        # Matches the real document exactly — every article's own cartons
        # are numbered from 01, independently of any other line (never a
        # running count across the whole Packing List).
        for line in self:
            n = line.carton_qty or 0
            if n <= 0:
                line.carton_range = False
            elif n == 1:
                line.carton_range = '01'
            else:
                line.carton_range = '01-%02d' % n

    @api.onchange('qty', 'qty_per_carton')
    def _onchange_suggest_cartons(self):
        if self.qty and self.qty_per_carton:
            self.carton_qty = math.ceil(self.qty / self.qty_per_carton)

    @api.onchange('pi_line_id', 'qty')
    def _onchange_preview_fg_amount(self):
        # Live, pre-save preview only — no claims are created here (an
        # unsaved line has no id to attach them to). The real, authoritative
        # value is set by _reema_allocate_claims() once the line is saved.
        allocation, _shortfall = self._reema_compute_allocation()
        self.fg_amount = float_round(
            sum(batch._reema_fg_value(take) for batch, take in allocation), precision_digits=2
        )

    def _reema_compute_allocation(self):
        """(list of (batch, qty) pairs, unmet qty) — oldest-produced batches
        first. Pure read, no writes; shared by the live onchange preview and
        the real claim-creation below."""
        self.ensure_one()
        if not self.pi_line_id or float_compare(self.qty or 0.0, 0.0, precision_digits=2) <= 0:
            return [], 0.0
        batches = self._reema_eligible_batches().filtered(
            lambda b: float_compare(b.qty_remaining, 0.0, precision_digits=2) > 0
        )
        remaining_needed = self.qty
        allocation = []
        for batch in batches:
            if float_compare(remaining_needed, 0.0, precision_digits=2) <= 0:
                break
            take = min(remaining_needed, batch.qty_remaining)
            allocation.append((batch, take))
            remaining_needed -= take
        return allocation, remaining_needed

    def _reema_allocate_claims(self):
        self.ensure_one()
        Claim = self.env['reema.packing.list.line.batch']
        self.batch_claim_ids.sudo().unlink()
        allocation, shortfall = self._reema_compute_allocation()
        if float_compare(shortfall, 0.0, precision_digits=2) > 0:
            article = self.pi_line_id.description or self.pi_line_id.sample_name or self.pi_line_id.display_name
            raise UserError(_(
                'Only %(avail).2f units of "%(article)s" (order %(order)s) are produced '
                'and ready to ship — requested %(qty).2f.'
            ) % {
                'avail': self.qty - shortfall, 'article': article,
                'order': self.pi_line_id.invoice_id.name, 'qty': self.qty,
            })
        if not allocation:
            self.fg_amount = 0.0
            return
        claims = Claim.sudo().create([
            {'line_id': self.id, 'batch_entry_id': batch.id, 'qty': take}
            for batch, take in allocation
        ])
        self.fg_amount = float_round(sum(claims.mapped('fg_amount')), precision_digits=2)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Force these now rather than trust the ORM's deferred-compute
        # queue — _reema_allocate_claims() below touches several other
        # models (claims, batches) in the same transaction, and that
        # activity was observed to silently drop the pending recompute for
        # these fields, leaving Description/Color/Size blank on create.
        records._compute_pi_fields()
        for rec in records:
            rec._reema_allocate_claims()
            rec.packing_list_id._reema_sync_commercial_invoice_no(invoices=rec.invoice_id)
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'qty' in vals or 'pi_line_id' in vals:
            for rec in self:
                rec._reema_allocate_claims()
        if 'invoice_id' in vals:
            for rec in self:
                rec.packing_list_id._reema_sync_commercial_invoice_no(invoices=rec.invoice_id)
        return res

    @api.constrains('pi_line_id', 'invoice_id')
    def _check_invoice_matches_article(self):
        for line in self:
            if line.pi_line_id and line.pi_line_id.invoice_id != line.invoice_id:
                raise UserError(_(
                    'Article "%(article)s" belongs to order %(real)s, not %(picked)s.'
                ) % {
                    'article': line.pi_line_id.display_name,
                    'real': line.pi_line_id.invoice_id.name,
                    'picked': line.invoice_id.name,
                })

    @api.constrains('qty')
    def _check_qty_positive(self):
        for line in self:
            if float_compare(line.qty, 0.0, precision_digits=2) <= 0:
                raise UserError(_('Quantity must be greater than zero.'))

    @api.constrains('pi_line_id', 'packing_list_id')
    def _check_pi_line_unique(self):
        for line in self:
            if not line.pi_line_id:
                continue
            siblings = line.packing_list_id.line_ids.filtered(
                lambda l: l.pi_line_id == line.pi_line_id and l.id != line.id
            )
            if siblings:
                raise UserError(_(
                    '"%s" is already on this Packing List — adjust its quantity '
                    'instead of adding it twice.'
                ) % (line.pi_line_id.description or line.pi_line_id.sample_name or line.pi_line_id.display_name))


class ReemaPackingListLineBatch(models.Model):
    _name = 'reema.packing.list.line.batch'
    _description = 'Packing List Line — Batch Allocation'

    line_id = fields.Many2one(
        'reema.packing.list.line', string='Article Line', required=True, ondelete='cascade',
    )
    packing_list_id = fields.Many2one(related='line_id.packing_list_id', string='Packing List', store=True)
    batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Batch', required=True, ondelete='restrict',
    )
    qty = fields.Float(string='Qty', required=True)
    fg_amount = fields.Float(string='FG Value', compute='_compute_fg_amount', digits=(10, 2))

    @api.depends('batch_entry_id.fg_account_move_id', 'qty')
    def _compute_fg_amount(self):
        for claim in self:
            claim.fg_amount = claim.batch_entry_id.sudo()._reema_fg_value(claim.qty)

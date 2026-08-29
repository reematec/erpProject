from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_round


def _reema_qty_str(value):
    return ('%.6f' % (value or 0.0)).rstrip('0').rstrip('.')


def _reema_compress_box_ranges(box_nos, pad):
    """[1,2,3,5,6] -> '01-03, 05-06' — same contiguous-range/zero-padding
    convention as the printed report, so what you see on the Articles tab
    matches what prints on the document."""
    if not box_nos:
        return False
    nos = sorted(box_nos)
    ranges = []
    start = prev = nos[0]
    for n in nos[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    parts = [
        str(a).zfill(pad) if a == b else '%s-%s' % (str(a).zfill(pad), str(b).zfill(pad))
        for a, b in ranges
    ]
    return ', '.join(parts)


class ReemaWoBatchEntryBoxPackingList(models.Model):
    _inherit = 'reema.wo.batch.entry'

    box_packing_claim_ids = fields.One2many(
        'reema.box.packing.list.claim', 'batch_entry_id', string='Box Packing Claims',
    )


class ReemaBoxPackingList(models.Model):
    _name = 'reema.box.packing.list'
    _description = 'Box Packing List — Finished Goods to COGS (mixed-article boxes)'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, tracking=True,
        domain=[('customer_rank', '>', 0)],
        help='A Box Packing List always belongs to one client — it can bundle '
             'several of that client\'s orders, but never more than one client.',
    )
    client_address = fields.Text(string='Client Address')
    container_no = fields.Char(string='Container Number')
    commercial_invoice_no = fields.Char(
        string='Commercial Invoice No.', tracking=True,
        help='Cross-reference to the Commercial Invoice covering this '
             'shipment — links this Box Packing List and its Pro Forma '
             'Invoice(s) together under one shipment reference.',
    )
    article_ids = fields.One2many('reema.box.packing.list.article', 'box_packing_id', string='Articles')
    box_ids = fields.One2many('reema.box.packing.list.box', 'box_packing_id', string='Boxes')
    total_boxes = fields.Integer(string='Total Boxes', compute='_compute_total_boxes', store=True)
    net_weight = fields.Float(
        string='Net Weight (kg)', digits=(10, 2), compute='_compute_weights', store=True,
        help='Sum of each article\'s qty × its product\'s own weight.',
    )
    gross_weight = fields.Float(
        string='Gross Weight (kg)', digits=(10, 2), compute='_compute_weights', store=True,
        help='Net Weight + the empty weight of every box.',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    account_move_id = fields.Many2one('account.move', string='COGS Entry', readonly=True, copy=False)
    total_amount = fields.Float(
        string='Total COGS', compute='_compute_total_amount', digits=(10, 2),
    )

    @api.depends('article_ids.fg_amount')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.article_ids.mapped('fg_amount'))

    @api.depends('box_ids.carton_qty')
    def _compute_total_boxes(self):
        for rec in self:
            rec.total_boxes = sum(rec.box_ids.mapped('carton_qty'))

    @api.depends('article_ids.qty', 'article_ids.sample_id.weight_kg',
                 'box_ids.carton_weight', 'box_ids.carton_qty')
    def _compute_weights(self):
        for rec in self:
            net = sum(article.qty * article.sample_id.weight_kg for article in rec.article_ids)
            packaging = sum(box.carton_weight * box.carton_qty for box in rec.box_ids)
            rec.net_weight = net
            rec.gross_weight = net + packaging

    def _reema_sync_commercial_invoice_no(self, invoices=None):
        """Push this Box Packing List's Commercial Invoice No. onto the Pro
        Forma Invoice(s) it actually ships (via its articles' own
        invoice_id). One Commercial Invoice covers one physical shipment,
        so its number belongs on every order that shipment includes —
        auto-filled here instead of relying on someone typing it correctly
        twice."""
        for rec in self:
            if not rec.commercial_invoice_no:
                continue
            targets = invoices if invoices is not None else rec.article_ids.mapped('invoice_id')
            stale = targets.filtered(lambda inv: inv.commercial_invoice_no != rec.commercial_invoice_no)
            if stale:
                stale.write({'commercial_invoice_no': rec.commercial_invoice_no})

    @api.onchange('partner_id')
    def _onchange_partner_id_address(self):
        if self.partner_id:
            self.client_address = self.partner_id._display_address()

    def copy(self, default=None):
        # Blocked outright, not just hidden from the UI — a duplicated Box
        # Packing List would copy article lines that immediately re-claim
        # already-shipped batch quantity, corrupting qty_remaining and COGS
        # for every batch involved. Start a fresh one instead.
        raise UserError(_(
            'Box Packing Lists can\'t be duplicated — start a new one instead.'
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
                'Commercial Invoice No. can only be set once the Box Packing List is Confirmed.'
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
            raise UserError(_('Only a draft Box Packing List can be confirmed.'))
        if not self.article_ids:
            raise UserError(_('Add at least one article before confirming.'))
        if not self.box_ids:
            raise UserError(_('Add at least one box before confirming.'))

        empty_boxes = self.box_ids.filtered(lambda b: not b.line_ids)
        if empty_boxes:
            raise UserError(_(
                'Carton run(s) %s have no contents — remove them or add articles to them.'
            ) % ', '.join(b.carton_range or _('(new)') for b in empty_boxes))

        # Hard reconciliation check — every article's ordered qty must match
        # what actually got placed into boxes, so a miscount while entering
        # box contents by hand can't slip through unnoticed.
        mismatches = []
        for article in self.article_ids:
            if float_compare(article.packed_qty, article.qty, precision_digits=2) != 0:
                mismatches.append(_(
                    '%(article)s: ordered %(qty).2f, packed %(packed).2f'
                ) % {
                    'article': article.description or article.pi_line_id.display_name,
                    'qty': article.qty, 'packed': article.packed_qty,
                })
        if mismatches:
            raise UserError(_(
                'Packed quantity does not match ordered quantity for:\n%s'
            ) % '\n'.join(mismatches))

        # sudo: confirming a Box Packing List needs to read the batches' own
        # Accounting entries regardless of the confirming user's direct
        # Manufacturing/Accounting access — same reasoning as the existing
        # Packing List (batches stay invisible to whoever is packing/shipping).
        Account = self.env['account.account'].sudo()
        fg_acc = Account.search([('code', '=', '1-1-7-04')], limit=1)
        material_cogs_acc = Account.search([('code', '=', '5-1-1-01')], limit=1)
        consumable_cogs_acc = Account.search([('code', '=', '5-1-1-02')], limit=1)
        if not (fg_acc and material_cogs_acc and consumable_cogs_acc):
            raise UserError(_('Missing Finished Goods (1-1-7-04), Raw Material Consumed (5-1-1-01) '
                               'or Production Consumables Consumed (5-1-1-02) account.'))

        if self.name == 'New':
            self.name = self.env['ir.sequence'].next_by_code('reema.box.packing.list') or 'New'

        claims = self.article_ids.mapped('batch_claim_ids')
        if not claims:
            raise UserError(_('Nothing to post — no article on this Box Packing List has a quantity allocated.'))

        line_vals = []
        for claim in claims:
            entry = claim.batch_entry_id.sudo()
            article = claim.article_id.pi_line_id
            fg_move = entry.fg_account_move_id
            if not fg_move or fg_move.state != 'posted':
                raise UserError(_(
                    'Batch "%s" has not been converted to Finished Goods yet — '
                    'cannot include it on a Box Packing List.'
                ) % entry.name)
            if not entry.reema_po_id or entry.reema_po_id.partner_id != self.partner_id:
                raise UserError(_(
                    'Batch "%(batch)s" belongs to a different client than this '
                    'Box Packing List (%(client)s).'
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

            label = f'Box Packing List {self.name} — {article.description or article.sample_name or article.sample_id.name or entry.name}'
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
                        'Box Packing List.'
                    ) % (hall.name if hall else _('Unknown')))
                line_vals.append((0, 0, {
                    'account_id': hall.expense_account_id.id,
                    'name': f'{label} — {hall.name}',
                    'debit': labor_amount, 'credit': 0.0,
                    'reema_batch_entry_id': entry.id,
                    'reema_source_workcenter_id': hall.id,
                }))

        if not line_vals:
            raise UserError(_('Nothing to post — every article on this Box Packing List has zero value.'))

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
            'Box Packing List confirmed — %(amount).2f moved from Finished Goods to COGS (entry %(move)s).'
        ) % {'amount': self.total_amount, 'move': move.name})

    def action_cancel(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Only a confirmed Box Packing List can be cancelled.'))
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
        self.message_post(body=_('Box Packing List cancelled — COGS entry reversed.'))

    def action_print_box_packing_list(self):
        if not self:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/report/html/reema_mrp.report_box_packing_list/%s' % ','.join(str(i) for i in self.ids),
            'target': 'new',
        }


class ReemaBoxPackingListArticle(models.Model):
    _name = 'reema.box.packing.list.article'
    _description = 'Box Packing List — Article Line'
    _order = 'box_packing_id, sequence, id'

    box_packing_id = fields.Many2one('reema.box.packing.list', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)

    def _compute_display_name(self):
        # This model has no 'name' field, so without this override any
        # Many2one pointing at it (e.g. article_id on the box Contents
        # list) falls back to Odoo's raw "model,id" default — meaningless
        # to read in a dropdown. Show the article + order instead.
        for article in self:
            label = article.description or (article.pi_line_id.display_name if article.pi_line_id else False) or _('Article')
            article.display_name = f'{label} ({article.invoice_id.name})' if article.invoice_id else label

    # Order first, article second — picking the order narrows the Article
    # dropdown to that order's own lines.
    invoice_id = fields.Many2one(
        'reema.invoice', string='Order', required=True,
        domain="[('partner_id', '=', parent.partner_id)]",
        options="{'no_open': True, 'no_create': True, 'no_edit': True}",
    )

    # The ordered article — a specific PI line, always scoped to one specific
    # order: traceability/payment-processing requirement.
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
    qty = fields.Float(string='Qty', help='Total quantity of this article being shipped on this Box Packing List.')
    box_line_ids = fields.One2many(
        'reema.box.packing.list.box.line', 'article_id', string='Box Placements',
        help='Every box row this article has actually been placed into.',
    )
    packed_qty = fields.Float(
        string='Packed', compute='_compute_box_stats', store=True,
        help='Sum of this article\'s quantity across every box it has been '
             'placed into — must match Qty before this Box Packing List can '
             'be confirmed.',
    )
    box_count = fields.Integer(
        string='Cartons', compute='_compute_box_stats', store=True,
        help='How many separate boxes this article has actually been placed into.',
    )
    box_numbers = fields.Char(
        string='Carton Nos.', compute='_compute_box_stats', store=True,
        help='Which box numbers this article is actually in — check this against '
             'the Boxes tab if Packed looks off.',
    )
    fg_amount = fields.Float(
        string='FG Value', digits=(10, 2), readonly=True,
        help='Live preview until saved (from the current allocation across '
             'available batches); the real, final value is fixed once the '
             'line is saved and its batch allocation is locked in.',
    )
    batch_claim_ids = fields.One2many(
        'reema.box.packing.list.claim', 'article_id', string='Batch Allocation', readonly=True,
        help='Which underlying production batch(es) this shipped quantity is '
             'actually drawn from — allocated automatically (oldest-produced '
             'first); not meant to be picked by hand.',
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
        # is building a Box Packing List — they shouldn't need direct
        # Manufacturing access just for this lookup to resolve behind the scenes.
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
        for article in self:
            po_lines = article._reema_source_po_lines()
            article.product_id = po_lines[:1].mo_id.product_id

    @api.depends('pi_line_id', 'batch_claim_ids.qty')
    def _compute_available_qty(self):
        for article in self:
            if not article.pi_line_id:
                article.available_qty = 0.0
                continue
            batches = article._reema_eligible_batches()
            own_claimed = sum(article.batch_claim_ids.mapped('qty'))
            article.available_qty = sum(batches.mapped('qty_remaining')) + own_claimed

    @api.depends('pi_line_id')
    def _compute_pi_fields(self):
        for article in self:
            line = article.pi_line_id
            article.sample_code = line.sample_code or False
            article.description = line.description or line.sample_name or line.sample_id.name or False
            article.sample_color = line.sample_color or False
            article.hs_code = line.hs_code or False
            article.ean = line.ean or False
            article.client_sku = line.client_sku or False
            article.size = line.size or False

    @api.depends('box_line_ids.qty', 'box_line_ids.box_id.carton_qty',
                 'box_line_ids.box_id.box_no_start', 'box_line_ids.box_id.box_no_end',
                 'box_packing_id.total_boxes')
    def _compute_box_stats(self):
        # A Contents line's qty is PER BOX in its run — this article's real
        # packed total across a run is qty × however many boxes that run
        # covers, and the box numbers it occupies are the run's whole
        # box_no_start..box_no_end range, not just one number.
        for article in self:
            packed = 0.0
            box_nos = set()
            for line in article.box_line_ids:
                run = line.box_id
                packed += (run.carton_qty or 0) * line.qty
                if run.carton_qty:
                    box_nos.update(range(run.box_no_start, run.box_no_end + 1))
            article.packed_qty = packed
            sorted_nos = sorted(box_nos)
            article.box_count = len(sorted_nos)
            total_boxes = article.box_packing_id.total_boxes or len(sorted_nos)
            pad = max(2, len(str(total_boxes))) if total_boxes else 2
            article.box_numbers = _reema_compress_box_ranges(sorted_nos, pad)

    @api.onchange('pi_line_id', 'qty')
    def _onchange_preview_fg_amount(self):
        # Live, pre-save preview only — no claims are created here (an
        # unsaved article has no id to attach them to). The real,
        # authoritative value is set by _reema_allocate_claims() once saved.
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
        Claim = self.env['reema.box.packing.list.claim']
        self.batch_claim_ids.sudo().unlink()
        allocation, shortfall = self._reema_compute_allocation()
        if float_compare(shortfall, 0.0, precision_digits=2) > 0:
            article_label = self.pi_line_id.description or self.pi_line_id.sample_name or self.pi_line_id.display_name
            raise UserError(_(
                'Only %(avail).2f units of "%(article)s" (order %(order)s) are produced '
                'and ready to ship — requested %(qty).2f.'
            ) % {
                'avail': self.qty - shortfall, 'article': article_label,
                'order': self.pi_line_id.invoice_id.name, 'qty': self.qty,
            })
        if not allocation:
            self.fg_amount = 0.0
            return
        claims = Claim.sudo().create([
            {'article_id': self.id, 'batch_entry_id': batch.id, 'qty': take}
            for batch, take in allocation
        ])
        self.fg_amount = float_round(sum(claims.mapped('fg_amount')), precision_digits=2)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Force these now rather than trust the ORM's deferred-compute
        # queue — _reema_allocate_claims() below touches several other
        # models (claims, batches) in the same transaction, and that
        # activity was observed (on the existing Packing List) to silently
        # drop the pending recompute for these fields, leaving
        # Description/Color/Size blank on create.
        records._compute_pi_fields()
        for rec in records:
            rec._reema_allocate_claims()
            rec.box_packing_id._reema_sync_commercial_invoice_no(invoices=rec.invoice_id)
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'qty' in vals or 'pi_line_id' in vals:
            for rec in self:
                rec._reema_allocate_claims()
        if 'invoice_id' in vals:
            for rec in self:
                rec.box_packing_id._reema_sync_commercial_invoice_no(invoices=rec.invoice_id)
        return res

    @api.constrains('pi_line_id', 'invoice_id')
    def _check_invoice_matches_article(self):
        for article in self:
            if article.pi_line_id and article.pi_line_id.invoice_id != article.invoice_id:
                raise UserError(_(
                    'Article "%(article)s" belongs to order %(real)s, not %(picked)s.'
                ) % {
                    'article': article.pi_line_id.display_name,
                    'real': article.pi_line_id.invoice_id.name,
                    'picked': article.invoice_id.name,
                })

    @api.constrains('qty')
    def _check_qty_positive(self):
        for article in self:
            if float_compare(article.qty, 0.0, precision_digits=2) <= 0:
                raise UserError(_('Quantity must be greater than zero.'))

    @api.constrains('pi_line_id', 'box_packing_id')
    def _check_pi_line_unique(self):
        for article in self:
            if not article.pi_line_id:
                continue
            siblings = article.box_packing_id.article_ids.filtered(
                lambda a: a.pi_line_id == article.pi_line_id and a.id != article.id
            )
            if siblings:
                raise UserError(_(
                    '"%s" is already on this Box Packing List — adjust its quantity '
                    'instead of adding it twice.'
                ) % (article.pi_line_id.description or article.pi_line_id.sample_name or article.pi_line_id.display_name))


class ReemaBoxPackingListBox(models.Model):
    # A row here is a RUN of identical physical boxes — carton_qty of them,
    # same size/weight/contents — not one record per physical box. Same
    # concept as the old Packing List's line (carton_size + qty_per_carton +
    # carton_qty), generalized so Contents can hold more than one article
    # (that's what makes mixed-article boxes possible). This is also why a
    # run can show its own "01-04"-style range as a plain field on the row —
    # no cross-record grouping needed, because one row already IS the range.
    _name = 'reema.box.packing.list.box'
    _description = 'Box Packing List — Carton Run'
    _order = 'sequence, id'

    box_packing_id = fields.Many2one('reema.box.packing.list', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    carton_size = fields.Char(string='Box Size', help='e.g. "40x30x30 cm"')
    carton_weight = fields.Float(string='Box Weight (kg)', digits=(10, 2), help='Empty-box weight, each.')
    carton_qty = fields.Integer(
        string='No. of Boxes', default=1, required=True,
        help='How many identical physical boxes this run covers — 1 for a one-off '
             '(e.g. a mixed or odd-sized last box), more for a run of identical '
             'single-article cartons. Contents below is PER BOX, not the run total.',
    )
    box_no_start = fields.Integer(string='From', compute='_compute_box_no_range', store=True)
    box_no_end = fields.Integer(string='To', compute='_compute_box_no_range', store=True)
    carton_range = fields.Char(
        string='Carton No.', compute='_compute_carton_range', store=True,
        help='This run\'s box numbers within the whole shipment, e.g. "01-04".',
    )
    line_ids = fields.One2many(
        'reema.box.packing.list.box.line', 'box_id', string='Contents',
        help='What goes in EACH box of this run — one row per article for a '
             'mixed box, or just one row for a single-article run.',
    )
    total_qty = fields.Float(
        string='Total Qty', compute='_compute_total_qty', store=True,
        help='No. of Boxes × the sum of Contents qty — the total across this whole run.',
    )
    contents_summary = fields.Char(
        string='Contents (per box)', compute='_compute_contents_summary', store=True,
        help='What\'s in EACH box of this run, at a glance — says "Mixed" when it holds '
             'more than one article, so you don\'t have to open a run to find out.',
    )
    is_mixed = fields.Boolean(
        string='Mixed', compute='_compute_contents_summary', store=True,
        help='More than one article is packed into each box of this run.',
    )

    @api.depends('carton_qty', 'sequence', 'box_packing_id.box_ids.carton_qty',
                 'box_packing_id.box_ids.sequence')
    def _compute_box_no_range(self):
        for bpl in self.mapped('box_packing_id'):
            runs_in_self = self.filtered(lambda r: r.box_packing_id == bpl)
            all_runs = bpl.box_ids.sorted(lambda r: (r.sequence, r.id))
            start = 1
            for run in all_runs:
                if run in runs_in_self:
                    run.box_no_start = start
                    run.box_no_end = start + (run.carton_qty or 0) - 1
                start += (run.carton_qty or 0)
        # Records with no box_packing_id yet (shouldn't normally happen,
        # it's required) fall back to a safe default instead of erroring.
        for run in self.filtered(lambda r: not r.box_packing_id):
            run.box_no_start = 1
            run.box_no_end = run.carton_qty or 1

    @api.depends('box_no_start', 'box_no_end', 'carton_qty', 'box_packing_id.total_boxes')
    def _compute_carton_range(self):
        for run in self:
            if not run.carton_qty:
                run.carton_range = False
                continue
            total = run.box_packing_id.total_boxes or run.box_no_end or 0
            pad = max(2, len(str(total)))
            if run.carton_qty == 1:
                run.carton_range = str(run.box_no_start).zfill(pad)
            else:
                run.carton_range = '%s-%s' % (str(run.box_no_start).zfill(pad), str(run.box_no_end).zfill(pad))

    @api.depends('line_ids.qty', 'carton_qty')
    def _compute_total_qty(self):
        for box in self:
            box.total_qty = (box.carton_qty or 0) * sum(box.line_ids.mapped('qty'))

    @api.depends('line_ids.qty', 'line_ids.article_id')
    def _compute_contents_summary(self):
        for box in self:
            if not box.line_ids:
                box.contents_summary = _('empty')
                box.is_mixed = False
                continue
            parts = sorted(
                ((line.article_id.display_name or '', line.qty) for line in box.line_ids),
                key=lambda t: t[0]
            )
            box.is_mixed = len(parts) > 1
            contents = ', '.join('%s x%s' % (name, _reema_qty_str(qty)) for name, qty in parts)
            box.contents_summary = (_('Mixed — %s') % contents) if box.is_mixed else contents

    def _reema_check_not_overpacked(self):
        for article in self.mapped('line_ids.article_id'):
            if float_compare(article.packed_qty, article.qty, precision_digits=2) > 0:
                raise UserError(_(
                    'Too much "%(article)s" packed into boxes: %(packed).2f packed vs. '
                    '%(qty).2f on this Box Packing List (%(over).2f over). Reduce a '
                    'run\'s No. of Boxes or Contents qty.'
                ) % {
                    'article': article.description or article.pi_line_id.display_name,
                    'packed': article.packed_qty, 'qty': article.qty,
                    'over': article.packed_qty - article.qty,
                })

    @api.constrains('carton_qty')
    def _check_carton_qty_not_overpacked(self):
        # Editing carton_qty alone (no Contents line touched) can still push
        # an article over its ordered total — Contents-line constrains won't
        # catch that since no box.line field actually changed.
        self._reema_check_not_overpacked()

    def action_delete_box(self):
        # A run is only ever reachable one at a time, opened as its own
        # dialog from the header's Boxes list — that list isn't editable
        # inline (it can't be, since a run's own Contents is itself a
        # one2many), so there's no per-row delete affordance there. This
        # button is the explicit, discoverable way to remove a run instead.
        self.ensure_one()
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}


class ReemaBoxPackingListBoxLine(models.Model):
    _name = 'reema.box.packing.list.box.line'
    _description = 'Box Packing List — Box Contents'
    _order = 'box_id, id'

    box_id = fields.Many2one('reema.box.packing.list.box', required=True, ondelete='cascade')
    article_id = fields.Many2one(
        'reema.box.packing.list.article', string='Article', required=True,
        options="{'no_open': True, 'no_create': True, 'no_edit': True}",
        help='Which article from this Box Packing List is in this box, and how many.',
    )
    product_id = fields.Many2one(related='article_id.product_id', string='Product', readonly=True)
    description = fields.Char(related='article_id.description', string='Description', readonly=True)
    client_sku = fields.Char(related='article_id.client_sku', string='SKU', readonly=True)
    sample_color = fields.Char(related='article_id.sample_color', string='Color', readonly=True)
    size = fields.Char(related='article_id.size', string='Size', readonly=True)
    qty = fields.Float(string='Qty', required=True, help='How many of this article go in EACH box of this run.')

    @api.constrains('qty')
    def _check_qty_positive(self):
        for line in self:
            if float_compare(line.qty, 0.0, precision_digits=2) <= 0:
                raise UserError(_('Quantity must be greater than zero.'))

    @api.constrains('qty', 'article_id')
    def _check_not_overpacked(self):
        # Deliberately on THIS model, not a cross-model constrain on the
        # Article listing box_line_ids — that didn't reliably fire when a
        # line was added via the box's own Contents list (verified: it let
        # an article go 75 over its ordered qty without a peep). A
        # constrains on the line itself, the model actually being written,
        # always fires. This ceiling is real: you can never ship more of an
        # article than is actually on this Box Packing List. Under-packed is
        # fine mid-draft; over-packed never is. (carton_qty changes are
        # caught separately, on the run itself — see
        # ReemaBoxPackingListBox._check_carton_qty_not_overpacked.)
        self.mapped('box_id')._reema_check_not_overpacked()

    @api.constrains('article_id', 'box_id')
    def _check_article_same_box_packing(self):
        for line in self:
            if line.article_id.box_packing_id != line.box_id.box_packing_id:
                raise UserError(_(
                    'Article "%(article)s" belongs to a different Box Packing List than run %(box)s.'
                ) % {'article': line.article_id.display_name, 'box': line.box_id.carton_range or _('(new)')})


class ReemaBoxPackingListClaim(models.Model):
    _name = 'reema.box.packing.list.claim'
    _description = 'Box Packing List Article — Batch Allocation'

    article_id = fields.Many2one(
        'reema.box.packing.list.article', string='Article Line', required=True, ondelete='cascade',
    )
    box_packing_id = fields.Many2one(related='article_id.box_packing_id', string='Box Packing List', store=True)
    batch_entry_id = fields.Many2one(
        'reema.wo.batch.entry', string='Batch', required=True, ondelete='restrict',
    )
    qty = fields.Float(string='Qty', required=True)
    fg_amount = fields.Float(string='FG Value', compute='_compute_fg_amount', digits=(10, 2))

    @api.depends('batch_entry_id.fg_account_move_id', 'qty')
    def _compute_fg_amount(self):
        for claim in self:
            claim.fg_amount = claim.batch_entry_id.sudo()._reema_fg_value(claim.qty)

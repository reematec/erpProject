from markupsafe import Markup
from odoo import _, fields, models
from odoo.tools.float_utils import float_round, float_is_zero


class AccountMoveFgExt(models.Model):
    _inherit = 'account.move'

    # Marks the Dr Finished Goods / Cr WIP entries created by Packing batch
    # conversion below — excluded when summing WIP-to-date for the moving-
    # average unit cost. Material issuance (reema_wip_costing.py) and labor
    # billing (reema_wo_batch.py) entries stay in that sum; this transfer-out
    # leg must not, or the average would shrink every time a batch converts,
    # corrupting the cost used for whatever packs next.
    is_fg_conversion = fields.Boolean(default=False, copy=False)


class AccountMoveLineFgExt(models.Model):
    _inherit = 'account.move.line'

    # Only set on the Labor WIP credit lines of a Packing FG-conversion entry
    # (_create_fg_conversion below), one per contributing hall. The ordinary
    # reema_workcenter_id (reema_wo_batch.py) is derived from
    # reema_batch_entry_id, which on these lines points at the PACKING batch
    # entry that triggered the conversion — that would make every split line
    # read back as "Packing" regardless of which hall the labor cost it's
    # crediting out actually came from. This field carries the real answer.
    reema_source_workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Original Hall', readonly=True,
        help='Which hall this portion of converted Labor WIP was originally '
             'billed at — needed to split Finished Goods back out by process '
             'when it converts to COGS at the Packing List step.',
    )


class ReemaWoBatchEntryFgCosting(models.Model):
    _inherit = 'reema.wo.batch.entry'

    fg_move_id = fields.Many2one('stock.move', string='FG Stock Move', readonly=True, copy=False)
    fg_account_move_id = fields.Many2one('account.move', string='FG Conversion Entry', readonly=True, copy=False)

    def _create_fg_conversion(self):
        """Packing-only: Dr Finished Goods / Cr WIP (Material + Labor), plus a
        matching physical stock move of the MO's real product into Finished
        Goods — both keyed off this batch's own qty, fired the moment a
        Packing batch is logged (Packing is confirmed last in every routing,
        and is where the real ready-to-ship count is known).

        Unit cost is a moving average recalculated at every packing batch:
        (all WIP ever debited to this MO, material + labor, net of returns —
        NOT net of prior FG conversions) / the MO's order quantity. Confirmed
        with the user: rework/repair postings that land on this MO after an
        earlier batch already converted to FG should raise the cost absorbed
        by whatever packs later, not retroactively restate what already
        shipped to FG.
        """
        self.ensure_one()
        wo = self.workorder_id
        wc = wo.workcenter_id
        if not wc.is_packing or self.qty <= 0:
            return False
        mo = self.mo_id
        if not mo or not mo.product_qty:
            return False

        Account = self.env['account.account']
        material_wip_acc = Account.search([('code', '=', '1-1-7-03')], limit=1)
        labor_wip_acc = Account.search([('code', '=', '1-1-7-07')], limit=1)
        consumable_wip_acc = Account.search([('code', '=', '1-1-7-08')], limit=1)
        fg_acc = Account.search([('code', '=', '1-1-7-04')], limit=1)
        if not (material_wip_acc and labor_wip_acc and fg_acc):
            self.mo_id._message_log(body=_(
                'FG conversion skipped — missing WIP/Finished Goods account setup.'
            ))
            return False

        AML = self.env['account.move.line']
        material_total = sum(AML.search([
            ('account_id', '=', material_wip_acc.id),
            ('move_id.reema_mo_id', '=', mo.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_fg_conversion', '=', False),
        ]).mapped(lambda l: l.debit - l.credit))
        labor_lines = AML.search([
            ('account_id', '=', labor_wip_acc.id),
            ('reema_mo_id', '=', mo.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_fg_conversion', '=', False),
        ])
        # Grouped by hall (reema_workcenter_id) — preserved through the whole
        # conversion, not collapsed into one number, so Labor can be split
        # back out by process at the Packing List/COGS step same as it always
        # could be split by process before it was deferred into WIP.
        labor_by_hall = {}
        for l in labor_lines:
            hall_key = l.reema_workcenter_id
            labor_by_hall[hall_key] = labor_by_hall.get(hall_key, 0.0) + (l.debit - l.credit)
        labor_total = sum(labor_by_hall.values())
        # Consumable WIP — posted by the month-end Consumable Stock Take
        # (reema_consumable_stock_take.py), tagged reema_consumable_mo_id
        # instead of a batch-entry-derived reema_mo_id, since one stock-take
        # line can spread its value across several MOs at once.
        consumable_total = 0.0
        if consumable_wip_acc:
            consumable_total = sum(AML.search([
                ('account_id', '=', consumable_wip_acc.id),
                ('reema_consumable_mo_id', '=', mo.id),
                ('move_id.state', '=', 'posted'),
                ('move_id.is_fg_conversion', '=', False),
            ]).mapped(lambda l: l.debit - l.credit))
        total_wip = material_total + labor_total + consumable_total
        if total_wip <= 0:
            self.mo_id._message_log(body=_(
                'FG conversion skipped — no WIP value posted yet for %(mo)s.'
            ) % {'mo': mo.name})
            return False

        unit_cost = total_wip / mo.product_qty
        amount = unit_cost * self.qty
        if float_is_zero(amount, precision_digits=2):
            return False
        material_portion = float_round(amount * (material_total / total_wip), precision_digits=2)
        consumable_portion = (
            float_round(amount * (consumable_total / total_wip), precision_digits=2)
            if consumable_total else 0.0
        )
        labor_portion = float_round(amount - material_portion - consumable_portion, precision_digits=2)

        # Split labor_portion back out across the halls that contributed to
        # labor_total, in the same proportion — rounding remainder goes on
        # the last hall so the split always sums exactly to labor_portion.
        hall_portions = []
        if labor_portion and labor_total:
            running = 0.0
            hall_items = [(hall, amt) for hall, amt in labor_by_hall.items() if amt]
            for i, (hall, amt) in enumerate(hall_items):
                if i == len(hall_items) - 1:
                    share = float_round(labor_portion - running, precision_digits=2)
                else:
                    share = float_round(labor_portion * (amt / labor_total), precision_digits=2)
                    running += share
                if share:
                    hall_portions.append((hall, share))

        journal = self.env['account.journal'].sudo().search(
            [('code', '=', 'STK'), ('company_id', '=', self.env.company.id)], limit=1
        )
        if not journal:
            self.mo_id._message_log(body=_('FG conversion skipped — no STK journal configured.'))
            return False

        label = f'Packing FG Conversion — {mo.name} / {self.name}'
        line_vals = [(0, 0, {
            'account_id': fg_acc.id, 'name': label,
            'debit': amount, 'credit': 0.0,
            'reema_batch_entry_id': self.id,
        })]
        if material_portion:
            line_vals.append((0, 0, {
                'account_id': material_wip_acc.id, 'name': label,
                'debit': 0.0, 'credit': material_portion,
                'reema_batch_entry_id': self.id,
            }))
        if consumable_portion:
            line_vals.append((0, 0, {
                'account_id': consumable_wip_acc.id, 'name': label,
                'debit': 0.0, 'credit': consumable_portion,
                'reema_batch_entry_id': self.id,
            }))
        for hall, share in hall_portions:
            hall_name = hall.name if hall else 'Unknown Hall'
            line_vals.append((0, 0, {
                'account_id': labor_wip_acc.id, 'name': f'{label} — {hall_name}',
                'debit': 0.0, 'credit': share,
                'reema_batch_entry_id': self.id,
                'reema_source_workcenter_id': hall.id if hall else False,
            }))
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': label,
            'reema_mo_id': mo.id,
            'is_fg_conversion': True,
            'line_ids': line_vals,
        })
        move.sudo().action_post()
        self.fg_account_move_id = move

        # Physical stock move — the MO's real product, not the generic "SFG
        # placeholder" every hall (including Packing) already tracks on its
        # own floor location. Separate move, existing SFG move is untouched.
        fg_location = self.env['stock.location'].search(
            [('complete_name', '=', 'WH/Finished Goods')], limit=1)
        if not fg_location:
            self.mo_id._message_log(body=_(
                'FG stock move skipped — WH/Finished Goods location not found.'
            ))
        else:
            source_loc = wc.location_id or self.env['stock.location'].search(
                [('usage', '=', 'production')], limit=1)
            stock_move = self.env['stock.move'].create({
                'name': f'FG: {mo.product_id.display_name}',
                'product_id': mo.product_id.id,
                'product_uom': mo.product_uom_id.id,
                'product_uom_qty': self.qty,
                'location_id': source_loc.id,
                'location_dest_id': fg_location.id,
                'origin': f'{mo.name} / {self.name}',
                'company_id': wo.company_id.id,
            })
            stock_move._action_confirm()
            stock_move.quantity = self.qty
            stock_move.move_line_ids.write({'picked': True})
            stock_move._action_done()
            self.fg_move_id = stock_move

        self.mo_id._message_log(body=Markup(
            f'<b>Finished Goods conversion</b> — {self.qty:.2f} x PKR {unit_cost:.2f} = '
            f'PKR {amount:.2f} (Material: {material_portion:.2f}, Labor: {labor_portion:.2f}, '
            f'Consumables: {consumable_portion:.2f})'
        ))
        return move

    def _reverse_fg_conversion(self):
        """Undo this entry's FG conversion side-effects (called from unlink,
        same pattern as _reverse_stock_moves for the SFG move) — a return
        stock move for the physical side, and a swapped-account account.move
        for the value side (matching reema_wip_costing.py's own return
        convention: a new offsetting entry, not a formal reversal wizard)."""
        self.ensure_one()
        if self.fg_move_id and self.fg_move_id.state == 'done':
            move = self.fg_move_id
            ret = self.env['stock.move'].create({
                'name': f'Return FG: {move.product_id.display_name}',
                'product_id': move.product_id.id,
                'product_uom': move.product_uom.id,
                'product_uom_qty': move.product_uom_qty,
                'location_id': move.location_dest_id.id,
                'location_dest_id': move.location_id.id,
                'origin': f'Return: {move.origin}',
                'company_id': move.company_id.id,
                'origin_returned_move_id': move.id,
            })
            ret._action_confirm()
            ret.quantity = ret.product_uom_qty
            ret.move_line_ids.write({'picked': True})
            ret._action_done()

        if self.fg_account_move_id and self.fg_account_move_id.state == 'posted':
            orig = self.fg_account_move_id
            reversal_lines = [(0, 0, {
                'account_id': line.account_id.id, 'name': line.name,
                'debit': line.credit, 'credit': line.debit,
                'reema_batch_entry_id': self.id,
                'reema_source_workcenter_id': line.reema_source_workcenter_id.id,
            }) for line in orig.line_ids]
            reversal = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': orig.journal_id.id,
                'date': fields.Date.context_today(self),
                'ref': f'Reversal: {orig.ref}',
                'reema_mo_id': orig.reema_mo_id.id,
                'is_fg_conversion': True,
                'line_ids': reversal_lines,
            })
            reversal.sudo().action_post()

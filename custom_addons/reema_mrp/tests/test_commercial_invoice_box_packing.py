from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCommercialInvoiceBoxPacking(TransactionCase):
    """Commercial Invoice <-> Box Packing List integration (2026-08-31 switch
    from the old Packing List). Covers: picking an existing confirmed Box
    Packing List, the standalone-entry auto-create path (placeholder box),
    the Boxes-tab real-breakdown path (transfer + reconciliation guard), the
    overpack guard, the double-invoice guard, and the Cancel cascade.

    Fixtures are built entirely from scratch (no reliance on the
    "ZZTEST DUMMY" manual-testing data living in the dev DB) so this suite
    stays valid after that data is eventually cleaned up.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env

        cls.partner = env['res.partner'].create({
            'name': 'Automated Test Client', 'customer_rank': 1,
        })

        product_tmpl = env['product.template'].create({
            'name': 'Automated Test Product', 'product_group': 'finished_good',
        })
        cls.product_type = env['reema.product.type'].create({
            'name': 'Automated Test Type',
            'sales_account_id': env['account.account'].search(
                [('account_type', '=', 'income')], limit=1).id,
        })
        cls.sample = env['reema.sampling.blueprint'].create({
            'product_tmpl_id': product_tmpl.id,
            'weight_range': '400 - 420 g',
            'product_type_id': cls.product_type.id,
        })

        cls.invoice = env['reema.invoice'].create({
            'name': 'Automated Test PI', 'partner_id': cls.partner.id,
        })
        cls.pi_line_1 = cls._make_pi_line(qty=100.0, price=2.0)
        cls.pi_line_2 = cls._make_pi_line(qty=60.0, price=3.0)

        cls.po = env['reema.production.order'].create({'invoice_id': cls.invoice.id})
        cls.workcenter = env['mrp.workcenter'].create({
            'name': 'Automated Test Packing WC', 'is_packing': True,
        })
        cls.batch_1 = cls._make_batch(cls.pi_line_1, qty=100.0)
        cls.batch_2 = cls._make_batch(cls.pi_line_2, qty=60.0)

    @classmethod
    def _make_pi_line(cls, qty, price):
        return cls.env['reema.invoice.line'].create({
            'invoice_id': cls.invoice.id,
            'sample_id': cls.sample.id,
            'description': 'Automated Test Article',
            'qty': qty,
            'price_unit': price,
        })

    @classmethod
    def _make_batch(cls, pi_line, qty):
        """A minimal but real reema.wo.batch.entry, already "Finished-Goods
        converted" (fg_account_move_id set to a posted move with a debit on
        1-1-7-04) — bypasses the real WIP-summing conversion flow
        (_create_fg_conversion), which needs actual posted WIP moves on the
        MO; only the resulting move matters to the code under test."""
        env = cls.env
        product = cls.sample.product_tmpl_id.product_variant_id
        mo = env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': qty,
            'product_uom_id': product.uom_id.id,
        })
        wo = env['mrp.workorder'].create({
            'name': 'Automated Test WO',
            'production_id': mo.id,
            'workcenter_id': cls.workcenter.id,
            'product_uom_id': mo.product_uom_id.id,
        })
        env['reema.production.order.line'].create({
            'order_id': cls.po.id,
            'invoice_line_id': pi_line.id,
            'sample_id': cls.sample.id,
            'mo_id': mo.id,
        })
        batch = env['reema.wo.batch.entry'].create({
            'workorder_id': wo.id,
            'qty': qty,
        })
        fg_acc = env['account.account'].search([('code', '=', '1-1-7-04')], limit=1)
        wip_acc = env['account.account'].search([('code', '=', '1-1-7-03')], limit=1)
        stk_journal = env['account.journal'].search([('code', '=', 'STK')], limit=1)
        move = env['account.move'].create({
            'move_type': 'entry',
            'journal_id': stk_journal.id,
            'date': fields.Date.today(),
            'line_ids': [
                (0, 0, {'account_id': fg_acc.id, 'name': 'Test FG', 'debit': qty * 1.5, 'credit': 0.0}),
                (0, 0, {'account_id': wip_acc.id, 'name': 'Test WIP', 'debit': 0.0, 'credit': qty * 1.5}),
            ],
        })
        move.action_post()
        batch.fg_account_move_id = move.id
        return batch

    def _make_confirmed_box_packing_list(self):
        """A real, already-confirmed Box Packing List — for tests of the
        "pick an existing list" path, as opposed to the standalone-entry
        auto-create path covered elsewhere in this file."""
        bpl = self.env['reema.box.packing.list'].create({
            'partner_id': self.partner.id,
        })
        article_1 = self.env['reema.box.packing.list.article'].create({
            'box_packing_id': bpl.id,
            'invoice_id': self.invoice.id,
            'pi_line_id': self.pi_line_1.id,
            'qty': 100.0,
        })
        self.env['reema.box.packing.list.box'].create({
            'box_packing_id': bpl.id,
            'carton_qty': 4,
            'line_ids': [(0, 0, {'article_id': article_1.id, 'qty': 25.0})],
        })
        bpl.action_confirm()
        return bpl

    # ── Picking an existing confirmed Box Packing List ──────────────────────

    def test_pick_existing_box_packing_list_populates_lines_and_locks_them(self):
        bpl = self._make_confirmed_box_packing_list()

        f = Form(self.env['reema.commercial.invoice'])
        f.partner_id = self.partner
        f.box_packing_id = bpl
        ci = f.save()

        self.assertEqual(len(ci.line_ids), 1)
        line = ci.line_ids
        self.assertEqual(line.pi_line_id, self.pi_line_1)
        self.assertEqual(line.qty, 100.0)
        self.assertTrue(line.box_article_id)

        # Hand-editing a qty pulled in from the Box Packing List is blocked.
        with self.assertRaises(UserError):
            line.qty = 50.0

    def test_double_invoice_guard(self):
        bpl = self._make_confirmed_box_packing_list()
        self.env['reema.commercial.invoice'].create({
            'partner_id': self.partner.id,
            'box_packing_id': bpl.id,
        })
        with self.assertRaises(UserError):
            self.env['reema.commercial.invoice'].create({
                'partner_id': self.partner.id,
                'box_packing_id': bpl.id,
            })

    # ── Standalone entry, no Box Packing List picked ────────────────────────

    def _make_standalone_ci(self, with_boxes=False):
        ci = self.env['reema.commercial.invoice'].create({'partner_id': self.partner.id})
        l1 = self.env['reema.commercial.invoice.line'].create({
            'ci_id': ci.id, 'invoice_id': self.invoice.id, 'pi_line_id': self.pi_line_1.id,
            'qty': 100.0, 'price_unit': self.pi_line_1.price_unit,
        })
        l2 = self.env['reema.commercial.invoice.line'].create({
            'ci_id': ci.id, 'invoice_id': self.invoice.id, 'pi_line_id': self.pi_line_2.id,
            'qty': 60.0, 'price_unit': self.pi_line_2.price_unit,
        })
        if with_boxes:
            self.env['reema.commercial.invoice.box'].create({
                'ci_id': ci.id, 'carton_qty': 2, 'carton_size': '40x30x30cm', 'carton_weight': 1.5,
                'line_ids': [(0, 0, {'article_id': l1.id, 'qty': 50.0})],
            })
            self.env['reema.commercial.invoice.box'].create({
                'ci_id': ci.id, 'carton_qty': 1, 'carton_size': '30x20x20cm', 'carton_weight': 0.8,
                'line_ids': [(0, 0, {'article_id': l2.id, 'qty': 60.0})],
            })
        return ci, l1, l2

    def test_standalone_placeholder_flow_confirms_and_posts(self):
        ci, l1, l2 = self._make_standalone_ci(with_boxes=False)
        ci.action_confirm()

        self.assertEqual(ci.state, 'confirmed')
        bpl = ci.box_packing_id
        self.assertTrue(bpl)
        self.assertEqual(bpl.auto_created_ci_id, ci)
        self.assertEqual(bpl.state, 'confirmed')
        self.assertEqual(len(bpl.box_ids), 1)
        self.assertEqual(bpl.box_ids.carton_qty, 1)
        for article in bpl.article_ids:
            self.assertEqual(article.qty, article.packed_qty)

        self.assertEqual(ci.account_move_id.state, 'posted')
        self.assertEqual(bpl.account_move_id.state, 'posted')

    def test_standalone_real_box_breakdown_transfers_correctly(self):
        ci, l1, l2 = self._make_standalone_ci(with_boxes=True)
        ci.action_confirm()

        bpl = ci.box_packing_id
        self.assertEqual(len(bpl.box_ids), 2)
        run1, run2 = bpl.box_ids.sorted(lambda r: r.sequence or r.id)
        self.assertEqual(run1.carton_qty, 2)
        self.assertEqual(run1.carton_size, '40x30x30cm')
        self.assertEqual(run1.carton_weight, 1.5)
        self.assertEqual(run1.carton_range, '01-02')
        self.assertEqual(run1.line_ids.qty, 50.0)

        self.assertEqual(run2.carton_qty, 1)
        self.assertEqual(run2.carton_range, '03')
        self.assertEqual(run2.line_ids.qty, 60.0)

        for article in bpl.article_ids:
            self.assertEqual(article.qty, article.packed_qty)

    def test_boxes_tab_mismatch_blocks_confirm(self):
        ci, l1, l2 = self._make_standalone_ci(with_boxes=False)
        # Only half of l1's qty gets a box — deliberately under-packed.
        self.env['reema.commercial.invoice.box'].create({
            'ci_id': ci.id, 'carton_qty': 1,
            'line_ids': [(0, 0, {'article_id': l1.id, 'qty': 50.0})],
        })
        with self.assertRaises(UserError):
            ci.action_confirm()
        # Nothing should have been created on the failed attempt.
        self.assertFalse(
            self.env['reema.box.packing.list'].search([('auto_created_ci_id', '=', ci.id)])
        )

    def test_boxes_tab_overpack_guard_blocks_at_create(self):
        ci, l1, l2 = self._make_standalone_ci(with_boxes=False)
        with self.assertRaises(UserError):
            self.env['reema.commercial.invoice.box'].create({
                'ci_id': ci.id, 'carton_qty': 5,
                # 5 boxes x 50 = 250, l1 is only 100 — over.
                'line_ids': [(0, 0, {'article_id': l1.id, 'qty': 50.0})],
            })

    def test_cancel_cascades_to_auto_created_box_packing_list(self):
        ci, l1, l2 = self._make_standalone_ci(with_boxes=False)
        ci.action_confirm()
        bpl = ci.box_packing_id

        ci.action_cancel()

        self.assertEqual(ci.state, 'cancelled')
        self.assertEqual(bpl.state, 'cancelled')

from odoo import api, models


class IrUiMenuReema(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        menu_ids = super()._visible_menu_ids(debug=debug)

        user = self.env.user
        is_supervisor_only = (
            user.has_group('reema_mrp.group_reema_supervisor')
            and not user.has_group('reema_mrp.group_reema_production_manager')
            and not user.has_group('reema_mrp.group_reema_store')
            and not user.has_group('stock.group_stock_manager')
        )
        if is_supervisor_only:
            stock_root = self.env.ref('stock.menu_stock_root', raise_if_not_found=False)
            if stock_root and stock_root.id in menu_ids:
                menu_ids = menu_ids - {stock_root.id}

        return menu_ids

import json

from odoo import api, models, _


class ReportProducts(models.AbstractModel):
    # HTML preview report for the Inventory > Products list. Mirrors the MO /
    # Piece Rate reports (report_type qweb-html, opened in a new tab via an
    # act_url, with an in-page screen-only Print/Close toolbar).
    #
    # It reflects whatever the list is currently SHOWING: the live search
    # domain (filters) and grouping are passed as query params by the list's
    # Print button (see static/src/views/product_name_nav_list.js). With no
    # filter/grouping the domain is the plain action domain, i.e. everything on
    # screen.
    _name = 'report.reema_mrp.report_products'
    _description = 'Products Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        Product = self.env['product.template']

        # Resolve the records: explicit docids win; otherwise use the domain the
        # list passed (its current filtered state).
        if docids:
            domain = [('id', 'in', docids)]
        else:
            domain = []
            raw_domain = data.get('domain')
            if raw_domain:
                try:
                    domain = json.loads(raw_domain)
                except (ValueError, TypeError):
                    domain = []

        # Grouping: first groupby field drives the section breakdown (strip any
        # ":granularity" suffix that date groupings carry).
        groupby = [g.split(':')[0] for g in (data.get('groupby') or '').split(',') if g]

        order = ', '.join(groupby + ['name']) if groupby else 'name'
        products = Product.search(domain, order=order)

        groups = []
        if groupby:
            field_name = groupby[0]
            field = Product._fields.get(field_name)
            selection_map = {}
            if field and field.type == 'selection':
                selection_map = dict(field._description_selection(self.env))

            buckets = {}
            ordered_keys = []
            for product in products:
                value = product[field_name] if field else False
                if field and field.type == 'many2one':
                    label = value.display_name if value else _('None')
                    key = value.id if value else 0
                elif field and field.type == 'selection':
                    label = selection_map.get(value, value) if value else _('None')
                    key = value or ''
                else:
                    label = value if value not in (False, None, '') else _('None')
                    key = label
                if key not in buckets:
                    buckets[key] = {'label': label, 'records': Product.browse()}
                    ordered_keys.append(key)
                buckets[key]['records'] |= product
            groups = [buckets[k] for k in ordered_keys]

        return {
            'doc_ids': products.ids,
            'doc_model': 'product.template',
            'docs': products,
            'company': self.env.company,
            'groupby_active': bool(groupby),
            'groups': groups,
        }

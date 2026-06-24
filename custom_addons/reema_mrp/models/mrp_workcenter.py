from odoo import models, fields


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    is_qc_point = fields.Boolean(
        string='Is QC Point', default=False,
        help='Marks this hall as a Quality Control (QC) department.\n\n'
             'QC halls are staffed by employees, not piece-rate contractors — '
             'so no contractor selection or piece-rate payment applies when '
             'batches are logged here.\n\n'
             'To activate this behaviour, also set Workforce Type to Employee. '
             'That setting is what actually suppresses the contractor and '
             'piece-rate fields during batch logging — this flag serves as '
             'the identifier that the hall is a QC stage.')
    is_packing = fields.Boolean(
        string='Is Packing Station', default=False,
        help='Enable for the Packing hall only.\n\n'
             'When batches are logged here, the Manufacturing Order automatically '
             'counts those balls as finished and ready. In practical terms: the number '
             'you enter in a packing batch directly becomes the "balls completed" figure '
             'on the production order.\n\n'
             'Only one hall per production line should have this enabled. '
             'If multiple halls are marked as Packing Station, their batch quantities '
             'will be added together — which will give an incorrect finished count.')
    is_ilo = fields.Boolean(
        string='ILO Work Center', default=False,
        help='Enable for halls that send balls to external ILO (hand-stitching) contractors.\n\n'
             'When enabled, the work order at this hall cannot be marked Done until '
             'every batch dispatched to ILO has been confirmed as received back. '
             'This prevents closing a production step while balls are still outside '
             'the factory.')
    is_printing = fields.Boolean(
        string='Printing Work Center', default=False,
        help='Enable for screen-printing (silk-screen) halls.\n\n'
             'When enabled:\n'
             '• Contractor payment is calculated per impression (daab) instead of per ball. '
             'The system multiplies Ball Qty × Impressions per Ball (from the BOM) to get '
             'total daab, then applies the piece rate.\n'
             '• The contractor bill for this hall will show three extra columns — '
             'Ball Qty, Impressions per Ball, and Total Impressions — so the payable '
             'amount can be cross-checked against the actual daab count.')
    hall_unit = fields.Selection([
        ('sheet', 'Sheet'),
        ('panel', 'Panel'),
        ('ball', 'Ball'),
    ], string='Logging Unit', default='ball', required=True,
        help='Physical unit batches are logged in at this hall, used to convert to balls:\n'
             '• Sheet (e.g. Lamination): balls = qty × Balls per Unit (set on the BOM operation).\n'
             '• Panel (e.g. Cutting, Printing, Sorting): balls = qty ÷ panels per ball '
             '(read from the product\'s sampling blueprint).\n'
             '• Ball (e.g. Stitching, Shaping, QC): logged directly in balls (1:1).')
    pay_basis = fields.Selection([
        ('ball', 'Per Ball'),
        ('hall', 'Per Hall Unit'),
    ], string='Pay Basis', default='ball', required=True,
        help='How contractor payment is calculated from batch log entries at this hall.\n\n'
             '• Per Ball — Contractor is paid for each finished ball produced.\n'
             '  Amount = Rate × Balls.\n'
             '  Use for halls where output is counted in balls: Stitching, Sorting,\n'
             '  Packing, Cleaning, Shaping, QC.\n'
             '  Note: Cutting logs in panels but pays Per Ball — the panel count is\n'
             '  only used for ball conversion, not for payment.\n\n'
             '• Per Hall Unit — Contractor is paid for each unit logged at this hall,\n'
             '  where the unit is whatever the Logging Unit above is set to.\n'
             '  Amount = Rate × Logged Qty.\n'
             '  For Printing halls, logged qty is automatically multiplied by the\n'
             '  BOM\'s Impressions / Ball to get total impressions (daab), since\n'
             '  payment is per daab not per ball.\n'
             '  Use for halls where payment is per impression or per sheet: Printing,\n'
             '  Lamination.')
    sfg_product_id = fields.Many2one('product.product', string='SFG Product Output',
                                     domain=[('product_group', '=', 'sfg')])
    location_id = fields.Many2one('stock.location', string='Hall Location',
                                  domain=[('usage', '=', 'internal')],
                                  help='Stock location for this hall. SFG products are moved here when a work order completes.')
    workforce_type = fields.Selection([
        ('contractor', 'Contractor'),
        ('employee', 'Employee'),
    ], string='Workforce Type', default='contractor', required=True)
    expense_account_id = fields.Many2one(
        'account.account',
        string='Labor Expense Account',
        domain=[('code', '=like', '5-2-1%')],
        help='Account debited when a contractor bill is posted for this work center.',
    )

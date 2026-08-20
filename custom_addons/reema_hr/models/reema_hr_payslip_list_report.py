from odoo import api, models

# Fallback column set (and order) when the report isn't given an explicit
# print_fields list — mirrors the list view's own field order.
DEFAULT_COLUMNS = [
    'name', 'employee_id', 'period_month', 'period_year',
    'monthly_salary', 'absent_deduction', 'half_day_deduction', 'gross_pay',
    'late_deduction', 'early_leave_deduction', 'advance_deduction', 'loan_deduction',
    'eobi_deduction', 'pessi_deduction', 'net_pay', 'state',
]


class ReportPayslipList(models.AbstractModel):
    # Summary/list report for Payslips — columns are chosen at print time from
    # whichever ones are currently visible in the list view (see
    # action_print_payslip / payslip_month_filter_list.js's onClickPrint,
    # which reads the on-screen <th data-name> attributes), not a fixed set.
    _name = 'report.reema_hr.report_payslip_list'
    _description = 'Payslip List Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['reema.hr.payslip'].browse(docids)
        data = data or {}
        fields_meta = docs._fields

        requested = data.get('print_fields') or ''
        if isinstance(requested, str):
            requested = [f for f in requested.split(',') if f]
        columns = [f for f in requested if f in fields_meta] or list(DEFAULT_COLUMNS)

        def format_cell(rec, fname):
            field = fields_meta[fname]
            value = rec[fname]
            if field.type == 'monetary':
                return '{:,.2f}'.format(value)
            if field.type == 'many2one':
                return value.display_name if value else ''
            if field.type == 'selection':
                return dict(field.selection).get(value) or ''
            if value is False:
                return ''
            return value

        # Title: "Payslips — July 2026" when every doc shares one period
        # (the overwhelmingly common case — printed straight from the
        # Month/Year picker), otherwise just "Payslips" rather than guessing
        # at a range.
        months = docs.mapped('period_month')
        years = docs.mapped('period_year')
        if len(set(months)) == 1 and len(set(years)) == 1:
            month_label = dict(fields_meta['period_month'].selection).get(months[0])
            title = 'Payslips — %s %s' % (month_label, years[0])
        else:
            title = 'Payslips'

        headers = [fields_meta[f].string for f in columns]
        # Right-align numeric-ish columns regardless of where the user put them
        # in the on-screen column order — alignment follows field TYPE, not position.
        alignments = ['text-end' if fields_meta[f].type in ('monetary', 'integer', 'float') else '' for f in columns]
        rows = [[format_cell(rec, f) for f in columns] for rec in docs]
        net_pay_col_index = columns.index('net_pay') if 'net_pay' in columns else None
        total_net_pay = '{:,.2f}'.format(sum(docs.mapped('net_pay'))) if net_pay_col_index is not None else None

        return {
            'doc_ids': docids,
            'doc_model': 'reema.hr.payslip',
            'docs': docs,
            'company': self.env.company,
            'title': title,
            'headers': headers,
            'alignments': alignments,
            'rows': rows,
            'col_count': len(columns),
            'net_pay_col_index': net_pay_col_index,
            'total_net_pay': total_net_pay,
        }

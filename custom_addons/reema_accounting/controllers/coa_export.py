import io
from datetime import date

import xlsxwriter

from odoo import http
from odoo.http import content_disposition, request

TYPE_LABELS = {
    'asset_receivable':      'Receivable',
    'asset_cash':            'Bank & Cash',
    'asset_current':         'Current Asset',
    'asset_non_current':     'Non-current Asset',
    'asset_prepayments':     'Prepayments',
    'asset_fixed':           'Fixed Asset',
    'liability_payable':     'Payable',
    'liability_current':     'Current Liability',
    'liability_non_current': 'Non-current Liability',
    'equity':                'Equity',
    'equity_unaffected':     'Current Year Earnings',
    'income':                'Income',
    'income_other':          'Other Income',
    'expense':               'Expense',
    'expense_depreciation':  'Depreciation',
    'expense_direct_cost':   'Cost of Revenue',
    'off_balance':           'Off Balance',
}


def _get_coa_data(env):
    groups_l1 = env['account.group'].search(
        [('parent_id', '=', False)], order='code_prefix_start'
    )
    all_accounts = env['account.account'].search([], order='code')
    accounts_by_group = {}
    for acc in all_accounts:
        key = acc.group_id.id if acc.group_id else 'ungrouped'
        accounts_by_group.setdefault(key, []).append(acc)
    return groups_l1, accounts_by_group


class COAExportController(http.Controller):

    # ── Preview page (standalone HTML + embedded PDF) ──────────────────

    @http.route('/reema/coa/preview', type='http', auth='user')
    def coa_preview(self, **kwargs):
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Chart of Accounts — Preview</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #e9ecef; font-family: sans-serif; overflow: hidden; }
        .toolbar {
            display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
            padding: 8px 14px; background: #343a40; color: white;
            position: fixed; top: 0; left: 0; right: 0; z-index: 999; min-height: 46px;
        }
        .toolbar-title { font-size: 15px; font-weight: 600; flex: 1; }
        .btn {
            display: inline-block; padding: 6px 13px; border-radius: 4px; border: none;
            cursor: pointer; font-size: 13px; text-decoration: none; font-family: inherit;
            white-space: nowrap; line-height: 1.4;
        }
        .btn-print  { background: #0d6efd; color: white; }
        .btn-export { background: #198754; color: white; }
        .btn-close  { background: #6c757d; color: white; }
        .btn:hover  { opacity: 0.85; }
        .pdf-frame  {
            position: fixed; top: 46px; left: 0; right: 0; bottom: 0;
            width: 100%; height: calc(100vh - 46px); border: none; display: block;
        }
    </style>
</head>
<body>
    <div class="toolbar">
        <span class="toolbar-title">Chart of Accounts</span>
        <button class="btn btn-print" onclick="
            (function(){
                var f = document.getElementById('pdfFrame');
                try { f.contentWindow.print(); }
                catch(e) {
                    var w = window.open('/report/html/reema_accounting.report_coa',
                        'coa_print', 'width=920,height=720,menubar=0,toolbar=0,scrollbars=1');
                    if (w) { w.addEventListener('load', function(){ w.focus(); w.print(); }); }
                }
            })()">&#128438; Print</button>
        <a class="btn btn-export"
           href="/report/pdf/reema_accounting.report_coa"
           download="Chart_of_Accounts.pdf">&#8615; PDF</a>
        <a class="btn btn-export" href="/reema/coa/export/xlsx">&#8615; Excel</a>
        <a class="btn btn-export" href="/reema/coa/export/rtf">&#8615; Word</a>
        <a class="btn btn-export" href="/reema/coa/export/md">&#8615; Markdown</a>
        <button class="btn btn-close" onclick="window.close()">&#10005; Close</button>
    </div>
    <iframe id="pdfFrame" class="pdf-frame"
            src="/report/pdf/reema_accounting.report_coa"
            title="Chart of Accounts">
        <p>PDF viewer not supported.
           <a href="/report/pdf/reema_accounting.report_coa">Download PDF</a></p>
    </iframe>
</body>
</html>"""
        return request.make_response(
            html,
            headers=[('Content-Type', 'text/html; charset=utf-8')]
        )

    # ── Excel ──────────────────────────────────────────────────────────

    @http.route('/reema/coa/export/xlsx', type='http', auth='user')
    def export_xlsx(self, **kwargs):
        env = request.env
        groups_l1, accounts_by_group = _get_coa_data(env)

        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        ws = wb.add_worksheet('Chart of Accounts')

        # Formats
        fmt_title  = wb.add_format({'bold': True, 'font_size': 14})
        fmt_date   = wb.add_format({'italic': True, 'font_color': '#555555'})
        fmt_header = wb.add_format({'bold': True, 'bg_color': '#343a40', 'font_color': '#ffffff',
                                    'border': 1})
        fmt_l1     = wb.add_format({'bold': True, 'font_size': 12, 'bg_color': '#d6dde3',
                                    'top': 2})
        fmt_l2     = wb.add_format({'bold': True, 'indent': 1})
        fmt_l3     = wb.add_format({'italic': True, 'indent': 2})
        fmt_acc    = wb.add_format({'font_name': 'Courier New', 'font_size': 10, 'indent': 3})
        fmt_acc_nm = wb.add_format({'indent': 3})
        fmt_type   = wb.add_format({'font_color': '#555555', 'indent': 3})

        ws.set_column('A:A', 28)
        ws.set_column('B:B', 42)
        ws.set_column('C:C', 22)

        r = 0
        ws.write(r, 0, 'Chart of Accounts', fmt_title)
        r += 1
        ws.write(r, 0, f"{env.company.name} — {date.today().strftime('%d %B %Y')}", fmt_date)
        r += 2

        for col, label in enumerate(['Code', 'Name', 'Type']):
            ws.write(r, col, label, fmt_header)
        r += 1

        def write_accounts(accs, code_fmt, name_fmt, type_fmt):
            nonlocal r
            for acc in accs:
                ws.write(r, 0, acc.code or '', code_fmt)
                ws.write(r, 1, acc.name or '', name_fmt)
                ws.write(r, 2, TYPE_LABELS.get(acc.account_type, ''), type_fmt)
                r += 1

        for g1 in groups_l1:
            ws.write(r, 0, g1.code_prefix_start or '', fmt_l1)
            ws.write(r, 1, g1.name or '', fmt_l1)
            ws.write(r, 2, '', fmt_l1)
            r += 1
            for g2 in g1.child_ids.sorted(key=lambda x: x.code_prefix_start):
                ws.write(r, 0, g2.code_prefix_start or '', fmt_l2)
                ws.write(r, 1, g2.name or '', fmt_l2)
                ws.write(r, 2, '', fmt_l2)
                r += 1
                for g3 in g2.child_ids.sorted(key=lambda x: x.code_prefix_start):
                    ws.write(r, 0, g3.code_prefix_start or '', fmt_l3)
                    ws.write(r, 1, g3.name or '', fmt_l3)
                    ws.write(r, 2, '', fmt_l3)
                    r += 1
                    write_accounts(accounts_by_group.get(g3.id, []), fmt_acc, fmt_acc_nm, fmt_type)
                write_accounts(accounts_by_group.get(g2.id, []), fmt_acc, fmt_acc_nm, fmt_type)
            write_accounts(accounts_by_group.get(g1.id, []), fmt_acc, fmt_acc_nm, fmt_type)

        if accounts_by_group.get('ungrouped'):
            ws.write(r, 0, 'Ungrouped', fmt_l1)
            ws.write(r, 1, '', fmt_l1)
            ws.write(r, 2, '', fmt_l1)
            r += 1
            write_accounts(accounts_by_group['ungrouped'], fmt_acc, fmt_acc_nm, fmt_type)

        wb.close()
        xlsx_bytes = buf.getvalue()

        return request.make_response(
            xlsx_bytes,
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition('Chart_of_Accounts.xlsx')),
            ],
        )

    # ── RTF (Word-compatible) ──────────────────────────────────────────

    @http.route('/reema/coa/export/rtf', type='http', auth='user')
    def export_rtf(self, **kwargs):
        env = request.env
        groups_l1, accounts_by_group = _get_coa_data(env)

        def esc(s):
            """Escape special RTF characters."""
            if not s:
                return ''
            return s.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')

        lines = [
            r'{\rtf1\ansi\deff0',
            r'{\fonttbl{\f0 Arial;}{\f1 Courier New;}}',
            r'{\colortbl ;\red85\green85\blue85;}',   # color1 = grey for type
            r'\widowctrl\wpaper12240\wpaperh15840\margl1440\margr1440\margt1440\margb1440',
            r'\f0\fs22',
            # Title
            r'{\pard\sb200\sa100\b\fs28 Chart of Accounts\b0\par}',
            (r'{\pard\sa200\i ' + esc(env.company.name) + r' \emdash  '
             + date.today().strftime('%d %B %Y') + r'\i0\par}'),
        ]

        def acc_lines(accs, indent_twips):
            for acc in accs:
                code = esc(acc.code or '')
                name = esc(acc.name or '')
                typ  = esc(TYPE_LABELS.get(acc.account_type, ''))
                lines.append(
                    r'{\pard\li' + str(indent_twips) + r'\sb0\sa0'
                    r'\f1\fs18 ' + code + r'\f0  ' + name
                    + (r'  {\cf1 ' + typ + r'}' if typ else '')
                    + r'\par}'
                )

        for g1 in groups_l1:
            lines.append(
                r'{\pard\sb160\sa0\li0\brdrb\brdrs\brdrw10\brsp20'
                r'\b\fs24 ' + esc(g1.code_prefix_start or '') + r'  ' + esc(g1.name or '') + r'\b0\par}'
            )
            for g2 in g1.child_ids.sorted(key=lambda x: x.code_prefix_start):
                lines.append(
                    r'{\pard\sb80\sa0\li360\b ' + esc(g2.code_prefix_start or '')
                    + r'  ' + esc(g2.name or '') + r'\b0\par}'
                )
                for g3 in g2.child_ids.sorted(key=lambda x: x.code_prefix_start):
                    lines.append(
                        r'{\pard\sb40\sa0\li720\i ' + esc(g3.code_prefix_start or '')
                        + r'  ' + esc(g3.name or '') + r'\i0\par}'
                    )
                    acc_lines(accounts_by_group.get(g3.id, []), 1080)
                acc_lines(accounts_by_group.get(g2.id, []), 720)
            acc_lines(accounts_by_group.get(g1.id, []), 360)

        if accounts_by_group.get('ungrouped'):
            lines.append(r'{\pard\sb160\sa0\li0\b\fs24 Ungrouped\b0\par}')
            acc_lines(accounts_by_group['ungrouped'], 360)

        lines.append('}')
        rtf_content = '\n'.join(lines)
        rtf_bytes = rtf_content.encode('latin-1', errors='replace')

        return request.make_response(
            rtf_bytes,
            headers=[
                ('Content-Type', 'application/rtf'),
                ('Content-Disposition', content_disposition('Chart_of_Accounts.rtf')),
            ],
        )

    # ── Markdown ───────────────────────────────────────────────────────

    @http.route('/reema/coa/export/md', type='http', auth='user')
    def export_md(self, **kwargs):
        env = request.env
        groups_l1, accounts_by_group = _get_coa_data(env)

        lines = [
            '# Chart of Accounts',
            '',
            f'**{env.company.name}** — {date.today().strftime("%d %B %Y")}',
            '',
        ]

        def acc_lines_md(accs, indent):
            for acc in accs:
                typ = TYPE_LABELS.get(acc.account_type, '')
                typ_str = f' _({typ})_' if typ else ''
                lines.append(f'{indent}- `{acc.code or ""}` {acc.name or ""}{typ_str}')

        for g1 in groups_l1:
            lines.append(f'## {g1.code_prefix_start}  {g1.name}')
            lines.append('')
            for g2 in g1.child_ids.sorted(key=lambda x: x.code_prefix_start):
                lines.append(f'### {g2.code_prefix_start}  {g2.name}')
                lines.append('')
                for g3 in g2.child_ids.sorted(key=lambda x: x.code_prefix_start):
                    lines.append(f'#### {g3.code_prefix_start}  {g3.name}')
                    lines.append('')
                    acc_lines_md(accounts_by_group.get(g3.id, []), '')
                    lines.append('')
                acc_lines_md(accounts_by_group.get(g2.id, []), '')
                if accounts_by_group.get(g2.id):
                    lines.append('')
            acc_lines_md(accounts_by_group.get(g1.id, []), '')
            if accounts_by_group.get(g1.id):
                lines.append('')

        if accounts_by_group.get('ungrouped'):
            lines.append('## Ungrouped')
            lines.append('')
            acc_lines_md(accounts_by_group['ungrouped'], '')

        md_content = '\n'.join(lines)
        md_bytes = md_content.encode('utf-8')

        return request.make_response(
            md_bytes,
            headers=[
                ('Content-Type', 'text/markdown; charset=utf-8'),
                ('Content-Disposition', content_disposition('Chart_of_Accounts.md')),
            ],
        )

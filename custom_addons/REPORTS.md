# Reema Reporting Standard

One convention for all reports across the reema modules, so "create a report for
module X" has a single, unambiguous meaning.

Reference implementations (study these):
- **Manufacturing Order** — `reema_mrp/views/reema_mo_report.xml`,
  `reema_mrp/models/reema_mo_report.py`, `mrp.production.action_print_mo`
- **Piece Rate** — `reema_mrp/views/reema_piece_rate_report.xml`,
  `reema.piece.rate.action_print_piece_rate_report`

---

## Default: HTML preview, browser-printed, opened in a new tab

Reports are **not** bound PDFs in the cog Print menu. They are HTML, opened in a
new browser tab from a button, and printed by the user with **Ctrl+P** (native
browser print). There is **no in-page Print/Close toolbar** — the user closes
the browser tab when done.

### 1. Trigger action (on the business model)
```python
def action_print_<thing>(self):
    if not self:
        return False
    return {
        'type': 'ir.actions.act_url',
        'url': '/report/html/<module>.report_<thing>/%s' % ','.join(str(i) for i in self.ids),
        'target': 'new',
    }
```
Works for one record (form) or several selected records (list).

### 2. Report action record (qweb-html, NOT bound)
```xml
<record id="action_report_<thing>" model="ir.actions.report">
    <field name="name">...</field>
    <field name="model"><model></field>
    <field name="report_type">qweb-html</field>
    <field name="report_name"><module>.report_<thing></field>
    <field name="report_file"><module>.report_<thing></field>
    <field name="print_report_name">'... - %s' % (object.name)</field>
</record>
```
No `binding_model_id` → stays out of the cog Print menu.

### 3. Data-prep model — only when computed data beyond record fields is needed
```python
class Report<Thing>(models.AbstractModel):
    _name = 'report.<module>.report_<thing>'
    _description = '...'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['<model>'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': '<model>',
            'docs': docs,
            'company': self.env.company,
            # ... extra maps, e.g. consumed_map ...
        }
```
Register in `models/__init__.py`.

### 4. Template skeleton
```xml
<template id="report_<thing>">
  <t t-call="web.html_container">
    <style>
      @media print {
        .<thing>_doc { page-break-after: always; }
        .<thing>_doc:last-child { page-break-after: auto; }
      }
      @page { margin: 12mm; }
    </style>
    <t t-foreach="docs" t-as="o">
      <t t-call="web.external_layout">
        <div class="page <thing>_doc">

          <!-- title block, detail tables, data tables -->
          <!-- No in-page toolbar: user prints with Ctrl+P, closes the tab. -->

        </div>
      </t>
    </t>
  </t>
</template>
```

### 5. Markup & styling rules
- **Branding** comes from `web.external_layout` (the shared folder layout +
  `external_layout_folder_reema` in `reema_mrp/views/report_layout_inherit.xml`).
  Never re-implement the company header/logo inline.
- **Font size**: use the **default report font** — do **not** set explicit
  `font-size` on the body or tables. Base is `1rem` (16px); Products and Piece
  Rate set none and are the reference look. Setting `12/13px` makes a report
  render visibly smaller than the others.
- **Title block**: use `<h3>` (and `<h5>` for the sub-reference), `<hr/>` separators — not inline font sizes.
- **Detail / key-value tables**: `table table-sm table-borderless`, `<strong>` label in left col (~45% width).
- **Data tables**: `table table-sm table-striped`; header `<thead><tr class="table-dark">`; numeric columns `class="text-end"` (Bootstrap 5 — **never** `text-right`).
- **Secondary / footnote text**: `<small class="text-muted">`.
- **Floats**: trim trailing zeros → `('%.6f' % val).rstrip('0').rstrip('.')`.
- **Values**: `t-field` for stored fields (auto-formats); `t-esc`/`t-out` for computed values.
- **Colors**: no per-report hardcoded hex — Bootstrap classes only (`table-dark`, `table-striped`, `text-muted`, `text-end`).
- **Spacing**: no per-report horizontal-spacing hacks (e.g. `body.container { padding:0 }`); left/right alignment is handled globally by the shared folder layout on print.

### 6. Files & registration
- Template + report action: `<module>/views/<thing>_report.xml`
- Data-prep AbstractModel (if any): `<module>/models/<thing>_report.py` (+ `models/__init__.py`)
- Register both in `<module>/__manifest__.py` `data`.

---

## Exception: official / archivable PDF documents

Invoice, Purchase Order, GRN — customer/vendor-facing documents that must be
saved as PDFs — stay:
- `report_type="qweb-pdf"`
- **with** `binding_model_id` + `binding_type="report"` (appear in the cog Print menu)
- with an explicit `paperformat_id`
- a shared signature snippet

…but reuse the **same body structure and table styling** as above (table-dark
header, `text-end` numerics, no ad-hoc hex colors).

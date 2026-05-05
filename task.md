## Guidelines for Tasks
1. When each task completes move it from Current Tasks to Completed Tasks.
2. Add the date when task is completed.
3. Briefly explain which operations, files, dependencies, and actions were performed for each task.
4. If one task is dependent on another task, prioritize it.
5. Put meaningful comments to explain each code, especially if it is complex.
6. Work on tasks in a tutorial way so the developer can learn as tasks are being executed. Explain the reason and what it will solve.
7. After each task is finished, verify no errors exist and the application is working.

## Current Tasks
[x] Charges in correct totals order + document file upload fix — Completed May 5, 2026.
    - Totals block restructured: Total Qty → Total Amount → [named charges inline] → Net Total Payable.
      Used Bootstrap col-6/ms-auto div to right-align, with tables above/below the charge_ids list.
      Each charge now appears individually between Total Amount and Net Total Payable.
    - Switched ReemaInvoiceDocument from fields.Binary to Many2many('ir.attachment').
      Files now stored in Odoo filestore (disk), not in PostgreSQL.
      Added file_count computed field for inline list display.
      Popup form uses widget="many2many_binary" — shows "Attach Files" button + preview/download links.
      Supports multiple files per document category.
    - Packing team access: discussed. Recommended Option A (read-only view in existing module,
      no new module) to implement when needed. Option B (reema_packing module) if packing staff
      need to write data (e.g. confirm shipment).
    - Files: reema_invoice.py, views/reema_invoice_views.xml.

[x] Packing team document access (Option A) — Completed May 5, 2026.
    - Added "Packing Staff" security group (group_reema_packing_user) to reema_invoice_security.xml,
      under the same Reema Invoice category as Export Staff.
    - Added read-only access in ir.model.access.csv for packing group:
      reema.invoice, reema.invoice.line, reema.invoice.document (read=1, write/create/unlink=0).
      No access to reema.invoice.charge or reema.bank.account (financial data).
    - Added packing list view (view_reema_invoice_packing_list): PI Number, Client, Order No,
      Shipping Date, Cartons, State. Filtered to accepted/closed invoices only.
    - Added packing form view (view_reema_invoice_packing_form): fully read-only (edit="0").
      Shows Order Details, Products tab (no Unit Price / Amount columns), and
      Shipping & Documents tab (logistics fields + document list with file counts).
      Bank Details tab is intentionally absent — no financial data for packing staff.
    - Added action_reema_invoice_packing with domain [('state', 'in', ['accepted','closed'])].
      Bound to packing-specific list and form views via ir.actions.act_window.view records.
    - Added "Packing Queue" menu under Pro Forma Invoices root, visible only to Packing Staff group.
    - Fixed duplicate-label warnings: total_charges string→"Total Charges"; file_count string→"File Count".
    - Files: security/reema_invoice_security.xml, security/ir.model.access.csv,
      views/reema_invoice_views.xml, models/reema_invoice.py.

[x] UI fixes — 2-column customer info, charge names, document bug — Completed May 5, 2026.
    - Customer Details split into 2 columns: Client/Address/Date on left, Order No/Order Date/
      Payment Terms on right. Done by nesting two <group> elements inside the parent group.
    - Removed "Additional Charges" aggregate from totals footer. Charges already visible
      individually by name in the charge_ids inline list above — no need to repeat them
      accumulated. Footer now shows Total Amount → Net Total Payable only.
    - Fixed document name disappearing bug: root cause was Binary widget inside editable
      inline list firing blur on click, which re-rendered the row from server (clearing unsaved
      name). Fix: removed Binary widget from inline list; the list now shows Document Name
      (editable) + Filename (read-only). A popup form (view_reema_invoice_document_form) handles
      the actual file upload safely — user types name inline, commits, then opens row to upload.
    - Files: reema_invoice.py (removed required=True from document name),
      views/reema_invoice_views.xml.


[x] Shipping tab, inline documents, inline charges, sample filter — Completed May 5, 2026.
    - Moved Shipping &amp; Terms from the main form into its own notebook tab, positioned
      between Products/Samples and Bank Details.
    - Added Carton &amp; Weight group in Shipping tab: Number of Cartons, Carton Size (L×W×H),
      Total CBM, Gross Weight (kg), Net Weight (kg).
    - Added inline Shipping Documents list (reema.invoice.document model): each row has a
      custom Document Name and a file upload (Binary). Supports any number of rows —
      Sticker, Hologram Layout, Carton Marking, etc.
    - Removed fixed handling_charges / courier_charges fields; replaced with inline
      Additional Charges list (reema.invoice.charge model): Description + Amount per row.
      Charges are optional — leave the list empty if none apply. net_total_payable
      recomputes from charge_ids.
    - Added domain filter on sample_id in invoice lines: only samples whose customer_id
      matches the selected client appear in the dropdown.
    - PDF report: added Packing Details section (cartons, CBM, weight); charges now loop
      over charge_ids with their custom names.
    - Files: reema_invoice.py (new models + fields), views/reema_invoice_views.xml,
      reports/reema_invoice_report.xml, security/ir.model.access.csv.




[x] Pro Forma Invoice Revision — Bank Details — Completed May 5, 2026.
    - Created reema.bank.account model (custom, no accounting link — Option A).
    - Fields: Bank Name, Account Title, Address, Account Number, IBAN, SWIFT, active.
    - Added bank_id Many2one to reema.invoice with onchange that auto-fills all bank detail fields.
    - Detail fields remain editable per-invoice for one-off overrides.
    - Bank Details tab now shows a "Select Bank" dropdown at the top, followed by the filled fields.
    - Added Configuration > Bank Accounts submenu under the Pro Forma Invoices menu for admin setup.
    - Export Staff users can read banks; only admins can create/edit/delete bank records.
    - Files: reema_invoice/models/reema_bank_account.py (new), models/__init__.py,
      reema_invoice.py, views/reema_invoice_views.xml, security/ir.model.access.csv.

[x] Sample Code — Name-first search and auto-fill — Completed May 5, 2026.
    - Reverted _rec_name override on ReemaSamplingBlueprint so dropdown shows product name (like Client field).
    - Kept _name_search override so typing a reference code also finds the sample.
    - Added sample_code Char field to reema.invoice.line; auto-fills with sample_id.reference via onchange.
    - Column order in invoice line: Name (sample_id Many2one, searchable) → Sample Code (auto-fill) → rest.
    - PDF report uses stored sample_code and sample_name fields for stability.

[x] Pro Forma Invoice Revision — Lines & Sample — Completed May 5, 2026.
    - Size field: removed Many2one size_id (reema.sampling.size.line), replaced with free-text Char `size`.
      Users can now type any size value (Size 5, Custom, XL) without being restricted to the sample's sizes.
    - Sample code search: added _rec_name='reference' to ReemaSamplingBlueprint so the dropdown shows
      reference codes. Added _name_search() override so users can still search by product name (easy to
      remember), and the reference auto-fills the Sample Code column on selection.
    - Color / HS Code / EAN editable: converted from related/readonly fields to plain Char fields.
      They pre-fill via _onchange_sample_id when a sample is selected, but can be overridden per line.
    - Description field: added Char `description` field to reema.invoice.line, visible in the line grid
      and in the PDF report.
    - Files changed: reema_sampling/models/reema_sampling_blueprint.py,
      reema_invoice/models/reema_invoice.py, reema_invoice/views/reema_invoice_views.xml,
      reema_invoice/reports/reema_invoice_report.xml.
    - Both modules upgraded with no errors.

[x] Invoice Module - Completed May 4, 2026.
    - Built reema_invoice module from scratch.
    - Form has two columns: "Customer Details" (Client, Address, PI Date, Client Order Number,
      Client Order Date, Payment Terms) and "Shipping and Terms" (Our Address, Country of Origin,
      Shipping Method, Shipping Date, Incoterms, Incoterm Location, Destination) — all visible
      on the main form, no hidden tabs.
    - Invoice lines: Sample Code, Name, Client SKU, Size, Color, HS Code, EAN, Qty, Unit Price,
      Amount. No taxes column. No "Add a Section/Note/Catalog" (custom model, not account.move).
    - Bank Details tab: Bank Name, Account Title, Bank Address, Account Number, IBAN, SWIFT.
    - Workflow: Pending → Sent → Accepted / Rejected → Closed. Print PI button in header.
    - Sequence: RG/YYYY-0001. Security group: Export Staff. User: Sameer Mehmood (sameer/sameer123).
    - PDF report includes all fields: addresses, order info, shipping, lines table, totals, bank.

<!-- [ ] Phase 5: Production Bridge ("Magic Button")
    - Add button to trigger BOM and Production Order generation.
    - Logic to map operations based on Construction Type (e.g., skip Turning for HS).
    - Logic to fetch Piece-Rates from matrix.
    - Note: On hold — focus on Invoice module first. -->

## Completed Tasks

[x] Implement Print Report for Sampling Blueprint - Completed May 4, 2026.
    - Created `reports/reema_sampling_report.xml` with a full QWeb PDF template.
    - Report includes: reference, customer, dates, status, technical specs, size table,
      material table, layout image (top-right), and general notes.
    - Updated `action_print_sampling()` in `reema_sampling_blueprint.py` to call
      `self.env.ref(...).report_action(self)` instead of the placeholder notification.
    - Registered report in `__manifest__.py` under data files.
    - Module upgraded with `-u reema_sampling` to load the new XML into the database.

[x] Bug Fixes — reema_sampling and reema_invoice - Completed May 4, 2026.
    - Added `<data noupdate="1">` wrapper to `reema_sampling_data.xml` to prevent
      sequence counter and user records from being reset on every module upgrade.
    - Deleted orphan files `data/ir_sequence_data.xml` and `data/res_users_data.xml`
      from reema_sampling — their content was already merged into reema_sampling_data.xml.
    - Removed `web_icon` attribute from root menuitems in both reema_sampling and
      reema_invoice views — no static/description/icon.png existed, causing 404 errors.

[x] Refine Invoice Module Features - Completed May 2, 2026.
    - Updated Invoice sequence to use prefix 'RG/YYYY-' (e.g., RG/2026-0001).
    - Added comprehensive Bank Details tab: Bank Name, Account Title, Address, A/C Number, IBAN, SWIFT.
    - Implemented enhanced workflow: Pending -> Sent -> Accepted/Rejected.
    - Restricted Customer field to existing records only (no_create, no_edit).
    - Added Client SKU field to invoice lines and integrated it into the PDF report.
    - Verified all changes with a clean Odoo registry load.

[x] Implement Reema Invoice Module (Pro Forma Invoice) - Completed May 2, 2026.
    - Created new module `reema_invoice`.
    - Implemented `reema.invoice` model with automatic PI sequencing.
    - Added auto-fill logic for Company and Client addresses.
    - Created `reema.invoice.line` model linked to `reema.sampling.blueprint`.
    - Implemented technical field auto-population (HS Code, EAN, Name, Color).
    - Restricted size selection to sample-specific sizes.
    - Designed professional PDF report.
    - Created security group "Reema Export Staff" and user Sameer Mehmood.

[x] Add color and HS Code fields to Sampling form - Completed May 2, 2026.
    - Added `color` and `hs_code` fields to `reema.sampling.blueprint`.
    - Updated form view to display them under Design Specification group.

[x] Completed samples must not appear in stock - Completed May 2, 2026.
    - Forced `type='consu'` (Consumable) on the product template via create/write override.

[x] Activity log (chatter) not visible on Sampling form - Completed May 2, 2026.
    - Added `mail.thread` and `mail.activity.mixin` to the model and chatter block to the view.

[x] Dashboard, Manufacturing, Production, Inventory not visible - Completed May 2, 2026.

[x] Fix sequence indexing in Sampling form - Completed April 30, 2026.

[x] Size, Cutting Knife, Quantity fields not accepting input - Completed April 30, 2026.

[x] Attachments & Layouts section must come before Size & Production - Completed April 30, 2026.

[x] Add layout image/PDF preview to Samples overview list - Completed April 30, 2026.

[x] Disable create/edit in Material field — selection only - Completed April 30, 2026.

[x] Make Size, Cutting Knife, Quantity inline fields (like Material lines) - Completed April 30, 2026.

[x] Add status fields: Completed, Shipped, Reference Piece Kept - Completed April 30, 2026.

[x] Move Technical Specification tab fields to main form - Completed April 30, 2026.

[x] Remove Category, Material Type, Base Material Color from Material tab - Completed April 30, 2026.

[x] Add quantity field to main Sampling form - Completed April 30, 2026.

[x] Add Print button to Sampling form - Completed April 30, 2026.

[x] Add detailed comments to reema_sampling code - Completed April 30, 2026.

[x] Rename Sampling form and overview labels - Completed April 30, 2026.

[x] Implement Sampling Blueprint Module (initial) - Completed April 29, 2026.

[x] Create user Kashif Ghauri - Completed April 29, 2026.

[x] Materials in sample must come from the product/material form - Completed April 29, 2026.

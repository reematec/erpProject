## Guidelines for Tasks
1. When each task completes move it from Current Tasks to Completed Tasks.
2. Add the date when task is completed.
3. Briefly explain which operations, files, dependencies, and actions were performed for each task.
4. If one task is dependent on another task, prioritize it.
5. Put meaningful comments to explain each code, especially if it is complex.
6. Work on tasks in a tutorial way so the developer can learn as tasks are being executed. Explain the reason and what it will solve.
7. After each task is finished, verify no errors exist and the application is working.

## Current Tasks
[ ] Pro Forma Invoice Revision
    - size field must be text, if already not in db, it allows to enter custom value. currently showing this. reema.sampling.size.line.5
    - sample code should fill from sample it is not easy to remember the codes, it easy to remember name so allow the user to search by name and both field from it.
    - colors must also be arbitrary field, it could be picked from sample original field but it also allow new values. HS code and Ean also not getting entered. 
    - line field must also have description field.
    - bank details must be selectable from predefined banks. user just select the bank and reset of the fields should fill up auto. just like customer is selected and his address fills up auto.  
    - discuss first before implementing on this task, if you need, you may create a form for defining the banks just like odoo default has feature to define company but before doing that let me know who it will connect to accounts and chart of accounts so i can thinks should it be done now, or later

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

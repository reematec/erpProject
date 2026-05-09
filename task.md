## Guidelines for Tasks
1. When each task completes move it from Current Tasks to Completed Tasks.
2. Add the date when task is completed.
3. Briefly explain which operations, files, dependencies, and actions were performed for each task.
4. If one task is dependent on another task, prioritize it.
5. Put meaningful comments to explain each code, especially if it is complex.
6. Work on tasks in a tutorial way so the developer can learn as tasks are being executed. Explain the reason and what it will solve.
7. After each task is finished, verify no errors exist and the application is working.

## Current Tasks

<!-- ═══════════════════════════════════════════════════════════════════════
     PHASE 1 — Foundation
     Goal: Invoice accepted → MOs appear on Waleed's dashboard with BOM
     pre-filled. Waleed confirms → Ali Shan sees Work Orders per hall.
════════════════════════════════════════════════════════════════════════ -->
[ ] Sampling Status buttons flow revision:
  - the flow buttons must be draft, in progress, Completed, Sample approved, Production ready.
  - Shipping must be separate from flow button and only activate one completed. it is possible that sample approved without shipping, just through images.

[ ] Create & Edit must be disabled in sampling blueprint.
[ ] In sampling BOM must activate when sample status is approved. Before that BOM Button must be disabled.
[ ] The client field in sample, remove create & Edit
[ ] the cancel button in MO and sample creates alot of confusion. I often think its the button to go back.

[ ] Fix "Production Order" button on Proforma Invoice — clarity + deduplication
    - Problem 1 — Ambiguous label: the button currently says "Production Order"
      regardless of whether a PO has been generated or not. It should say
      "Generate PO" when no PO exists, and "View PO" when one already exists.
    - Problem 2 — Duplicate placement: the button appears in two places on the
      invoice, causing confusion. Remove one and keep a single authoritative
      location.
    - Preferred location: in the form header area, either directly after the
      invoice reference number (oe_title area) or immediately after/before the
      "Print PI" button — whichever is more visible at first glance.
    - Implementation:
        * In reema_invoice views, find both button definitions and remove the
          duplicate.
        * Rename "Create Production Order" → "Generate PO" with
          invisible="production_order_count > 0"
        * Add "View PO" button with invisible="production_order_count == 0"
          that opens the linked PO (same action as existing smart button).
        * Keep the smart button in oe_button_box for count/navigation (that is
          fine), but remove any second standalone button elsewhere.
    - Files: reema_mrp/views/reema_production_order_views.xml and/or
      reema_invoice views (wherever the duplicate lives).

[ ] Change Manufacturing Order reference format from "WH/MO/00012" to "MO/2026/00012"
    - The default Odoo MO sequence produces "WH/MO/00012" which looks like a
      warehouse transfer or work order at first glance.
    - Change to "MO/%(year)s/xxxxx" format so it reads clearly as a Manufacturing
      Order with the year visible (e.g. MO/2026/00012).
    - Fix: update the ir.sequence record with code 'mrp.production' — change
      prefix from 'WH/MO/' to 'MO/%(year)s/' and set padding to 5.
    - This can be done via Settings → Technical → Sequences, or via a data XML
      record with noupdate="0" in reema_mrp to override the default sequence.
    - Existing MO numbers will not be renamed (Odoo sequences don't retroactively
      change already-assigned references) — only new MOs get the new format.

[ ] MO number in Production Order lines should be a clickable link
    - In the Production Order detail view (e.g. PO/2026/0036), the production
      lines tab shows a list of reema.production.order.line records.
    - The `mo_id` field (e.g. "WH/MO/00012") currently renders as plain readonly
      text in the list — clicking it does nothing.
    - Fix: make it a proper Many2one link so clicking the MO number opens the
      mrp.production record directly.
    - Change in reema_mrp/views/reema_production_order_views.xml — the mo_id
      field in the lines list (currently readonly="1") needs
      options="{'no_open': False}" or just remove no_open suppression so Odoo
      renders it as a navigable link.

[ ] BOM auto-reference number
    - mrp.bom has no reference field — BOMs are currently identified only by
      product name, which is ambiguous when a product has multiple BOMs (e.g.
      different revisions or construction types).
    - Add a `reema_reference` Char field on mrp.bom (inherited via MrpBomReemaExt
      in reema_mrp/models/reema_production_order.py).
    - Auto-assign on create using a new ir.sequence: prefix BOM/%(year)s/, padding 5.
    - Field must be readonly after creation (assigned once, never changed).
    - Show it in the BOM form view header (oe_title area) and BOM list view as
      first column so it is immediately visible.
    - Sequence record to add in reema_mrp/data/ir_sequence_data.xml.

[x] Phase 1.1 — Fix reema_mrp bugs — Completed May 5 2026
    - Duplicate line was a reporting artifact — actual code was fine.
    - wizard/ had only __pycache__ (source .py files deleted). Created
      wizard/__init__.py so the import works without cache dependency.
    - Added data/ir_sequence_data.xml to manifest data list so the
      BATCH sequence is loaded into the database on upgrade.
    - Fixed security: split base.group_user (full CRUD) into two rows —
      base.group_user (read-only) and base.group_system (full CRUD).
    - Fixed missing parent menu: reema_mrp_menu_config and
      reema_mrp_menu_root were referenced but never defined. Added
      "Production" root menu and "Configuration" submenu to
      reema_piece_rate_views.xml.
    - Module upgrades cleanly with EXIT: 0 and no errors.
    - Files: reema_mrp/wizard/__init__.py (new),
      reema_mrp/__manifest__.py, reema_mrp/security/ir.model.access.csv,
      reema_mrp/views/reema_piece_rate_views.xml

[x] Phase 1.2 — Add sample_approved and production_ready statuses to blueprint — Completed May 5 2026
    - Added sample_approved and production_ready to state field.
    - Contextual header buttons: Start / Mark Sample Approved / Mark Production Ready /
      Complete / Ship / Cancel / Reset to Draft.
    - action_sample_approved schedules a To-Do activity for Waleed to define BOM.
    - construction_type values changed to MRP abbreviations: ms/hyb/thb/hs.
      DB migration ran: existing record updated from 'machine_stitched' → 'ms'.
    - Files: reema_sampling/models/reema_sampling_blueprint.py,
      reema_sampling/views/reema_sampling_blueprint_views.xml

[x] Phase 1.3 — Smart button on blueprint → BOM — Completed May 5 2026
    - bom_count computed field; oe_button_box BOM button in blueprint form.
    - action_view_bom: 0 BOMs → new form pre-filled with blueprint materials (qty 1 each);
      1 BOM → open directly; 2+ → list view.
    - Inherited mrp.bom form in reema_mrp: removed Catalog button, hidden
      Product Attachment column to reduce clutter for Waleed.
    - Files: reema_sampling/models/reema_sampling_blueprint.py,
      reema_sampling/views/reema_sampling_blueprint_views.xml,
      reema_mrp/views/mrp_views.xml

[x] Phase 1.4 — Set up 17 Work Centers and SFG products — Completed May 9 2026
    - All 17 Work Centers configured in Manufacturing → Configuration → Work Centers.
    - SFG products created and assigned via sfg_product_id on each Work Center.
    - QC halls (13 and 16) marked with is_qc_point = True.
    - Data setup only — no custom code required.

[x] Phase 1.5 — SFG stock movement on work order completion — Completed May 7 2026
    - Added location_id field to mrp.workcenter (hall's own stock location).
    - Created "Production Halls" view location under WH with 13 child internal
      locations (one per hall that has an SFG product). Auto-assigned via shell.
    - Implemented button_finish override on MrpWorkorder: when a work order completes,
      creates a validated stock.move from Virtual/Production → hall's location_id
      for qty_produced units of the hall's sfg_product_id.
    - Halls with no sfg_product_id or no location_id are silently skipped
      (QC halls, ILO, Packing).
    - location_id field visible on Work Center form for manual review/adjustment.
    - Files: reema_mrp/models/mrp_workcenter.py, reema_mrp/models/mrp_workorder.py,
      reema_mrp/views/mrp_views.xml
    - Implement the stock movement in reema_mrp/models/mrp_workorder.py
      button_finish override (hook exists, logic not written)
    - When Ali Shan completes a work order:
        1. Deduct input SFG from WIP stock (previous hall's sfg_product_id)
        2. Add this hall's sfg_product_id to WIP stock (qty = qty_produced)
        3. Gap between input and output = waste/scrap at that stage
    - This gives full live WIP inventory tracking at every hall
    - Files: reema_mrp/models/mrp_workorder.py

[x] Phase 1.6 + 1.7 — Production Order button on invoice + PO model — Completed May 5 2026
    - reema.production.order model in reema_mrp (name, invoice_id, partner_id,
      state draft/confirmed/done/cancelled, date_planned, line_ids, mo_count).
    - reema.production.order.line model (sample_id, size, qty, bom_id, mo_id).
    - "Create Production Order" button on accepted invoice — hidden once PO exists.
      Button auto-fills PO lines from invoice lines + auto-detects BOM per blueprint.
    - Smart button on invoice shows PO count; Production > Production Orders menu added.
    - reema_mrp now depends on reema_invoice (manufacturing knows about invoices, not reverse).
    - Files: reema_mrp/models/reema_production_order.py (new),
      reema_mrp/views/reema_production_order_views.xml (new),
      reema_mrp/__manifest__.py, reema_mrp/data/ir_sequence_data.xml,
      reema_mrp/security/ir.model.access.csv

[x] Phase 1.5b — "Create MOs" button on Production Order — Completed May 6 2026
    - Added action_create_mos() on reema.production.order.
    - Loops through lines where bom_id is set AND mo_id is empty.
    - Creates mrp.production per line: product_id from BOM variant, qty, bom_id, origin=PO name.
    - Sets line.mo_id after creation. Raises UserError if nothing to process.
    - MO smart button always visible (shows 0 MOs as pending signal).
    - Files: reema_mrp/models/reema_production_order.py,
      reema_mrp/views/reema_production_order_views.xml

[x] Phase 1.5d — Enforce BOM Operation Dependencies — Completed May 6 2026
    - Problem 1: Waleed (or any future user) must manually tick "Operation Dependencies"
      checkbox in BOM Miscellaneous tab. Easy to forget, breaks work order sequencing silently.
    - Problem 2: MOs can be created from a BOM where nobody defined any "Blocked By" on
      operations — work orders start in wrong order or all at once.

    Fix 1 — Auto-enable on every new BOM:
    - Added MrpBomReemaExt class in reema_production_order.py inheriting mrp.bom.
    - Overrides allow_operation_dependencies default from False → True.
    - Every new BOM silently starts with operation dependencies enabled.

    Fix 2 — Hide the checkbox so it cannot be unchecked:
    - Added xpath in mrp_views.xml to set invisible=True on the
      allow_operation_dependencies field in BOM Miscellaneous tab.
    - Users cannot toggle it — it stays on permanently.

    Fix 3 — Block MO creation if no Blocked By is defined at all:
    - In action_create_mos(), before creating any MO, validates that each BOM
      with >1 operations has at least one operation with blocked_by_operation_ids set.
    - If ALL operations have no Blocked By → clear UserError naming the blueprint.
    - Parallel-track BOMs (multiple operations with no Blocked By) are allowed —
      only the case where nobody defined any dependency is blocked.
    - Why: strict "exactly one root" check would break valid parallel workflows
      in other manufacturing contexts (two halls running simultaneously then merging).
    - Files: reema_mrp/models/reema_production_order.py,
      reema_mrp/views/mrp_views.xml

[x] Phase 1.5c (partial) — Reset MO per line — Completed May 6 2026
    - Problem: BOM is incomplete when MOs are created (during initial setup this
      is common). Waleed needs to cancel the wrong MO and recreate it after fixing
      the BOM. Previous workaround required direct DB/shell access — not possible
      for Waleed.
    - Solution: added action_reset_mo() on reema.production.order.line.
      - If MO is in draft or confirmed: cancels it via action_cancel(), then deletes it (unlink).
        Deleting is safe because no work has been recorded yet.
      - If MO is in progress or done: raises UserError — cannot reset, coordinate with floor.
      - Clears mo_id on the line after deletion.
    - Added undo icon button (fa-undo) in the PO lines list, visible only when mo_id is set.
      Button shows a confirmation dialog before proceeding.
    - After reset, Waleed clicks "Create MOs" again — new MO created with the updated BOM.
    - Files: reema_mrp/models/reema_production_order.py,
      reema_mrp/views/reema_production_order_views.xml

[ ] Phase 1.5c (remaining) — Sync from Invoice on Production Order
    - Problem: Invoice quantities change after PO is created (client revision).
      PO lines stay on old quantities with no indication they're out of sync.
    - "Sync from Invoice" button visible when PO is confirmed
    - Compares each PO line qty against its invoice_line_id.qty
    - Updates PO line qty where they differ
    - If line has an MO: also updates mrp.production.product_qty on the linked MO
      (only if MO is still in draft — warn otherwise)
    - Files: reema_mrp/models/reema_production_order.py,
      reema_mrp/views/reema_production_order_views.xml

[x] Phase 1.4 — Set up 17 Work Centers (data setup) — Completed May 9 2026
    - All 17 halls created in Manufacturing → Configuration → Work Centers.
    - Data setup only — no code required.

[ ] Phase 1.8 — Role-based access control (all users)
    ─────────────────────────────────────────────────────
    ROLES TO DEFINE:

    Sampling Team (e.g. user: store)
      Group: group_reema_sampling_user  (in reema_sampling module)
      Access: Sampling menu only
        - reema.sampling.blueprint: read, write, create (no delete)
        - reema.sampling.size.line, reema.sampling.material.line: full
        - Cannot see: Invoices, Production, Manufacturing menus

    Production Manager (user: Waleed)
      Group: group_reema_production_manager  (in reema_mrp module)
      Access: Production + Sampling (read only) + Invoice (no prices/bank)
        - reema.sampling.blueprint: read only (to view specs/materials)
        - mrp.bom, mrp.bom.line: full (define and edit BOMs)
        - reema.production.order, reema.production.order.line: full
        - mrp.production, mrp.workorder: full
        - reema.invoice: read only, EXCLUDING price_unit, bank tab fields
        - Cannot see: Invoice create/edit, Bank Details tab

    Export Staff (user: Sameer) — already implemented
      Group: group_reema_export_staff  (in reema_invoice module — exists)
      Access: Invoices + Sampling (read only)
        - Already working. May need: cannot see Production Orders unless
          relevant for order status visibility — defer to feedback.

    Floor Supervisor (user: Ali Shan) — Phase 2
      Group: group_reema_floor_supervisor  (in reema_mrp module)
      Access: Work Orders only (tablet view)
        - mrp.workorder: read + write (mark done, enter qty)
        - Cannot see: BOM, Invoices, full MO form
        - Deferred to Phase 2.1 (floor interface)

    Finance (user: Irfan) — Phase 2-3
      Group: group_reema_finance  (in reema_mrp module)
      Access: Payables approval + reporting
        - Piece rate payables, contractor ledger
        - Deferred to Phase 2.3

    ─────────────────────────────────────────────────────
    IMPLEMENTATION STEPS (when planned):

    Step 1 — reema_sampling security group
      - Add reema_sampling_security.xml with group_reema_sampling_user
      - Restrict Sampling menu to this group + Admin
      - Update ir.model.access.csv: sampling models writable by sampling group
      - Files: reema_sampling/security/reema_sampling_security.xml (new),
        reema_sampling/security/ir.model.access.csv,
        reema_sampling/views/reema_sampling_blueprint_views.xml (menu group attr)

    Step 2 — reema_mrp production manager group
      - Add reema_mrp_security.xml with group_reema_production_manager
      - Production menu visible to production manager + Admin
      - Read-only invoice fields: use field-level groups or separate
        read-only view for invoice (no price_unit, no bank tab)
      - Files: reema_mrp/security/reema_mrp_security.xml (new),
        reema_mrp/security/ir.model.access.csv,
        reema_mrp/views/reema_production_order_views.xml

    Step 2b — Restrict Cancel MO and Delete on MO
      - Cancel MO button: visible only to Production Manager + Admin groups
        (currently visible to all — move to group-restricted visibility)
      - Delete MO (kebab/action menu): restrict via ir.rule or group access
        on mrp.production model — floor operators cannot delete MOs
      - File: reema_mrp/security/reema_mrp_security.xml (when created in Step 2)

    Step 3 — Assign existing users to groups
      - store user → group_reema_sampling_user
      - waleed user → group_reema_production_manager
      - sameer user → already in group_reema_export_staff
      - Verify each user can only see their designated menus

    Note: Developer mode must be enabled to manage users:
      http://localhost:8069/web?debug=1 → Settings → Users & Companies → Users


[x] Phase 1.5e — Material issuance block on work order start — Completed May 7 2026
    - Extended button_start on MrpWorkorderReema with a second hard block:
      checks mo.move_raw_ids — if ALL component moves are not 'done' (nothing issued),
      raises UserError naming the MO and directing supervisor to the Store Keeper.
    - Partial issue allowed: if at least one move is 'done', work order can start.
    - MOs with no raw material moves (no components) are unaffected.
    - Enforcement chain: Store Keeper skips entry → Supervisor blocked → escalates
      to Production Manager → Store Keeper interrogated → forced to validate.
    - File: reema_mrp/models/reema_production_order.py (MrpWorkorderReema.button_start)


<!-- ═══════════════════════════════════════════════════════════════════════
     PHASE A — Accounting, Finance & Procurement Foundation
     Goal: Full double-entry accounting, purchase cycle, and inventory
     valuation live. Must complete before go-live date.
     See DESIGN.md for full design decisions and rationale.
════════════════════════════════════════════════════════════════════════ -->

[ ] Phase A.1 — Install Accounting + Purchase + Pakistan Localization
    - In Odoo Apps: install "Accounting", "Purchase", "Pakistan - Accounting"
    - Accounting replaces basic Invoicing — enables full double-entry
    - Purchase enables PO → Receipt → Vendor Bill → Payment flow
    - Pakistan localization (l10n_pk) provides standard Chart of Accounts + tax config
    - Verify: Accounting menu appears, Purchase menu appears

[ ] Phase A.2 — Fiscal Year & Currency
    - Accounting → Configuration → Settings:
      - Fiscal Year: July 1 – June 30
      - Default Currency: PKR
      - Lock: no multi-currency needed (all transactions in PKR)
    - Create first fiscal year period if not auto-created

[ ] Phase A.3 — Chart of Accounts review
    - Pakistan localization installs a standard CoA automatically
    - In-house accountant reviews and renames/adds accounts to match Reema's books
    - Key accounts to confirm exist (see DESIGN.md → Chart of Accounts section)
    - Add if missing: Supplier Advances, Customer Advances, Labor Cost, Contractor Cash

[ ] Phase A.4 — Tax Configuration
    - Sales tax: zero-rated (0%) for all export sales — set as default on customer records
    - Purchase WHT: configure Section 153 tax (4.5% filer / 9% non-filer)
    - Add boolean field on supplier (res.partner): withholding_allowed
      (custom field — needed to flag suppliers who refuse WHT deduction)

[ ] Phase A.5 — Bank Journals & Cash Journals
    - Create one journal per bank account (2–3 accounts)
    - Create "Petty Cash" cash journal
    - Create "Contractor Cash" cash journal
    - Link each journal to its corresponding CoA account

[ ] Phase A.6 — Warehouse Sub-Locations
    - Inventory → Configuration → Locations
    - Under "Reema Warehouse / Input" (or equivalent):
      - Raw Material Store
      - Production Halls (parent, virtual)
        - One child location per hall (17 halls)
      - Finished Goods Store
      - Packing Area
    - Set correct usage type: Internal for all

[x] Phase A.0 — Product Group field on all products — Completed May 7 2026
    - Added product_group Selection field to product.template (in reema_mrp/models/reema_product.py)
    - Groups: Raw Material, Packaging, Semi-Finished Good, Finished Good
    - Field appears on product form (after Internal Category), product list (optional column)
    - Search view: 4 quick filters (one per group) + Group By option
    - sfg_product_id on Work Center form now restricted by domain to SFG products only
    - Indexed for fast filtering across large product lists
    - Files: reema_mrp/models/reema_product.py (new), reema_mrp/models/__init__.py,
      reema_mrp/views/mrp_views.xml

[ ] Phase A.7 — Product Categories with AVCO
    - Inventory → Configuration → Product Categories
    - "Raw Materials": Costing Method = Average Cost (AVCO), Inventory Valuation = Automated
    - "Finished Goods": Costing Method = Average Cost (AVCO), Inventory Valuation = Automated
    - Assign all existing raw material products to Raw Materials category
    - Assign finished goods products to Finished Goods category

[ ] Phase A.8 — User Roles & Access Rights
    - See Phase 1.8 detail already in this file (combined with manufacturing roles)
    - Add new roles for accounting/procurement staff: Accountant, Store Keeper, Gate
    - Accounting group: full Accounting module, no stock operations
    - Store Keeper group: Inventory receive/issue, Purchase receipt validation, no payments
    - Gate group: delivery in/out confirmation only


<!-- ═══════════════════════════════════════════════════════════════════════
     PHASE B — Procurement Cycle
     Goal: All supplier material purchases flow through Odoo with full
     3-way match: PO → Receipt → Bill → Payment.
════════════════════════════════════════════════════════════════════════ -->

[ ] Phase B.1 — Supplier Master Data
    - Create supplier records in Contacts for all raw material suppliers
    - Required fields per supplier: Name, NTN, Address, Bank Details
    - Add withholding_allowed flag (True/False) per supplier
    - Assign payment terms where applicable (credit vs cash)

[ ] Phase B.2 — Raw Material Products
    - Create product records for all raw materials: PU sheets, fabric, latex, thread,
      bladders, valves, panels, lining, etc.
    - Set product category → Raw Materials (AVCO)
    - Set correct Unit of Measure (kg, meters, pcs)
    - Set reorder rules if applicable

[ ] Phase B.3 — Purchase Flow Walkthrough
    - Test full cycle: Create PO → Receive goods (Store Keeper) → Create Bill
      (Accountant) → Register Payment
    - Verify AVCO cost updates on receipt
    - Verify journal entries at each step (see DESIGN.md → Procurement Flow)
    - Verify 3-way match: bill cannot be validated without matching PO and receipt

[ ] Phase B.4 — Advance Payment to Suppliers
    - Configure advance payment workflow:
      - Payment registered against supplier before PO receipt
      - Posted to "Supplier Advances" account (asset)
      - Cleared when bill is matched and payment applied
    - Test with a real supplier advance scenario


<!-- ═══════════════════════════════════════════════════════════════════════
     PHASE D — Sales & Export Accounting
     Goal: Pro Forma Invoice → Delivery → Export Invoice → Payment
     fully recorded in accounting.
════════════════════════════════════════════════════════════════════════ -->

[ ] Phase D.1 — Delivery Order linked to Pro Forma Invoice
    - When production is complete and goods are ready for export:
      create Delivery Order from Finished Goods Store
    - Link delivery to the Pro Forma Invoice

[ ] Phase D.2 — Export Invoice in Accounting
    - After delivery, create accounting invoice (account.move) linked to Pro Forma
    - Amount in PKR (rate applied externally)
    - Tax: zero-rated
    - Journal entry: Dr Accounts Receivable / Cr Sales Revenue

[ ] Phase D.3 — Customer Advance Payments
    - Configure advance from customer workflow:
      - Customer pays deposit before production starts
      - Posted to "Customer Advances" account (liability)
      - Cleared when final invoice is raised and payment applied

[ ] Phase D.4 — Customer Payment & Bank Reconciliation
    - Register PKR payment receipt against export invoice
    - Reconcile with bank statement


<!-- ═══════════════════════════════════════════════════════════════════════
     PHASE E — Controls & Go-Live
     Goal: Enforce all controls, enter opening balances, lock history,
     and train staff before going live.
════════════════════════════════════════════════════════════════════════ -->

[ ] Phase E.1 — Physical Inventory Workflow
    - Configure periodic inventory count process
    - Each hall location counted separately (WIP per hall)
    - Discrepancies require reason before adjustment is posted

[ ] Phase E.2 — Opening Balance Entry
    - On agreed go-live date, enter:
      1. Raw material stock quantities + AVCO unit cost
      2. Cash and petty cash balances
      3. Bank account balances
      4. Outstanding supplier payables
      5. Outstanding customer receivables
    - All entries dated the go-live date

[ ] Phase E.3 — Period Locking & User Training
    - Lock all accounting periods before go-live date (no back-dating)
    - Train each role on their specific screens and workflows
    - Verify each user can only access their designated areas


<!-- ═══════════════════════════════════════════════════════════════════════
     PHASE 2 — Production Floor & Costing
     Goal: Live WIP tracking, material consumption, piece-rate payables.
     Start only after Phase 1 is stable and team is using it daily.
════════════════════════════════════════════════════════════════════════ -->

[ ] Phase 2.1 — Ali Shan work order interface
    - Simple per-hall view showing Ali Shan only his current work orders
    - Mobile-friendly (used on tablet on the factory floor)
    - Shows: ball type, quantity, contractor, current hall
    - One button: "Mark Done" with qty field

[ ] Phase 2.2 — Material consumption at correct work order step
    - Configure "Consumed in Operation" on BOM components:
        Bladder → consumed at Hall 9 (Bladder Attachment)
        Foam Panel → consumed at Hall 7 (Foam Attachment, HYB only)
        Thread → consumed at Hall 6 (Stitching)
        PU + Fabric → consumed at Hall 2 (Lamination)
    - System deducts stock at the exact hall where material is physically used

[ ] Phase 2.3 — Piece rate matrix population and activation
    - After Phase 1 work centers are set up, Waleed fills piece rate matrix:
        Hall + construction type + ball size + complexity → rate per unit
    - Contractor payable auto-entry when work order is confirmed by Ali Shan
    - Irfan sees pending payables per contractor per week for approval

[ ] Phase 2.4 — QC pass / rework / reject buttons
    - Hall 13 (Initial QC) and Hall 16 (Final QC) get three buttons:
        Pass → ball moves to next hall, contractor cleared for payment
        Rework → ball sent back to previous hall, contractor flagged (no double pay)
        Reject → ball moved to B-Grade warehouse or Scrap location
    - System records rejection reason for monthly quality reports


<!-- ═══════════════════════════════════════════════════════════════════════
     PHASE 3 — Quality, HS & Advanced Costing
     Goal: Full production control, HS ball ILO tracking, accurate COGS.
     Start only after Phase 2 is stable.
════════════════════════════════════════════════════════════════════════ -->

[ ] Phase 3.1 — HS ball ILO contractor tracking
    - Printed Panel Sets issued to ILO contractors (outgoing transfer)
    - Stitched Shells received back (incoming transfer)
    - Gatekeeper interface: scan out / scan in
    - Track "in transit" quantity per contractor

[ ] Phase 3.2 — Yield gap variance reporting
    - Compare input vs output at each hall (detect waste/theft)
    - Variance posted to the Manufacturing Order
    - Monthly report: expected consumption vs actual per hall

[ ] Phase 3.3 — QC rejection cost redistribution
    - When balls are scrapped in Final QC, redistribute cost of
      scrapped balls across remaining good balls in the same MO
    - Use Scrap Entry within the Manufacturing Order

[ ] Phase 3.4 — Full COGS calculation per order
    - Raw material landed cost + cumulative piece rates + consumables
      + factory overhead absorption at Final QC stage
    - Cost report per invoice/client showing true margin




## Completed Tasks
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

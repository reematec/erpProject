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
     CLAUDE AI INTEGRATION — MCP Server for Odoo Development
     Goal: Connect Claude Code to the live Odoo instance so Claude can
     directly query models, inspect fields, read records, and tail logs
     during development sessions — no manual data relay needed.
════════════════════════════════════════════════════════════════════════ -->

[ ] Set up Odoo MCP Server for Claude Code

  WHAT IS AN MCP SERVER?
  MCP (Model Context Protocol) is a standard that lets Claude Code talk to
  external tools. We build a small Python server that wraps Odoo's XML-RPC API
  and exposes it as "tools" Claude can call during any development session.
  Once set up, you can say "search all mrp.production records in draft state"
  and Claude will query your live database directly.

  TOOLS THAT WILL BE AVAILABLE TO CLAUDE:
  ┌─────────────────────────────────────────────────────────────────────┐
  │ search_records(model, domain, fields, limit)  Query any model       │
  │ get_model_fields(model)                       Inspect field defs    │
  │ list_models(keyword)                          Browse all models     │
  │ get_record(model, id, fields)                 Read one record       │
  │ execute_method(model, method, ids, kwargs)    Call any method       │
  │ get_odoo_log(lines)                           Tail the Odoo log     │
  │ list_custom_modules()                         Custom addon states   │
  └─────────────────────────────────────────────────────────────────────┘

  CHECKLIST (do in order):

  [ ] Step 1 — Install mcp package into Odoo venv
      Command:
        /home/amir/erpProject/odoo-venv/bin/pip install mcp
      Note: Installs mcp 1.27.2 + ~21 deps. Zero conflicts with Odoo packages (confirmed).

  [ ] Step 2 — Create server file
      Create directory: /home/amir/erpProject/mcp_odoo/
      Create file:      /home/amir/erpProject/mcp_odoo/server.py
      Full file content is below (see SERVER CODE section).

  [ ] Step 3 — Add mcpServers block to .claude/settings.local.json
      File: /home/amir/erpProject/.claude/settings.local.json
      Add this block alongside the existing "permissions" key:

        "mcpServers": {
          "odoo": {
            "command": "/home/amir/erpProject/odoo-venv/bin/python",
            "args": ["/home/amir/erpProject/mcp_odoo/server.py"],
            "env": {
              "ODOO_URL": "http://localhost:8069",
              "ODOO_DB": "odoo18_sgo_football_dev",
              "ODOO_USER": "admin",
              "ODOO_PASSWORD": "FILL_THIS_IN"
            }
          }
        }

  [ ] Step 4 — ⚠️ USER ACTION: Fill in Odoo admin password
      Replace FILL_THIS_IN with the Odoo web login password for the admin user.
      This is the password used at http://localhost:8069/web — NOT:
        - db_password in odoo.conf (that is the PostgreSQL password)
        - admin_passwd hash in odoo.conf (that is the DB manager master password)

      To verify the password works:
        /home/amir/erpProject/odoo-venv/bin/python - <<'EOF'
        import xmlrpc.client
        common = xmlrpc.client.ServerProxy("http://localhost:8069/xmlrpc/2/common")
        uid = common.authenticate("odoo18_sgo_football_dev", "admin", "YOUR_PASSWORD", {})
        print("UID:", uid)  # non-zero integer = success, False = wrong password
        EOF

      To reset admin password if forgotten:
        /home/amir/erpProject/odoo-venv/bin/python \
          /home/amir/erpProject/odoo/odoo-bin \
          -c /home/amir/erpProject/odoo.conf \
          --stop-after-init --no-http \
          -d odoo18_sgo_football_dev shell <<'EOF'
        env['res.users'].browse(2).write({'password': 'newpassword123'})
        env.cr.commit()
        print("Password updated")
        EOF

  [ ] Step 5 — Smoke-test the server (before restarting Claude Code)
      Command:
        ODOO_PASSWORD=your_actual_password \
          /home/amir/erpProject/odoo-venv/bin/python \
          /home/amir/erpProject/mcp_odoo/server.py
      Expected: process starts and blocks (waiting for MCP messages via stdio).
      Press Ctrl-C to stop. If auth fails, a RuntimeError prints immediately.

  [ ] Step 6 — Restart Claude Code
      MCP servers are loaded only at startup. Fully exit and reopen Claude Code.

  [ ] Step 7 — Verify tools work (in new Claude Code session)
      Ask Claude:
        "Use list_custom_modules"
        "Use search_records with model='res.partner', domain=[], fields=['name'], limit=5"
        "Use get_model_fields for model='mrp.production'"
        "Use get_odoo_log with lines=10"

  ── SERVER CODE ──────────────────────────────────────────────────────────
  File: /home/amir/erpProject/mcp_odoo/server.py

  import os
  import xmlrpc.client
  from typing import Any
  from mcp.server.fastmcp import FastMCP

  ODOO_URL = os.environ.get("ODOO_URL", "http://localhost:8069")
  ODOO_DB = os.environ.get("ODOO_DB", "odoo18_sgo_football_dev")
  ODOO_USER = os.environ.get("ODOO_USER", "admin")
  ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD")

  if not ODOO_PASSWORD:
      raise RuntimeError("ODOO_PASSWORD env var is required.")

  _uid = None
  _common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
  _models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

  def _get_uid():
      global _uid
      if _uid is None:
          _uid = _common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
          if not _uid:
              raise RuntimeError(f"Odoo auth failed for '{ODOO_USER}' on '{ODOO_DB}'.")
      return _uid

  def _execute(model, method, *args, **kwargs):
      return _models.execute_kw(ODOO_DB, _get_uid(), ODOO_PASSWORD, model, method, list(args), kwargs)

  mcp = FastMCP("odoo")

  @mcp.tool()
  def search_records(model: str, domain: list, fields: list, limit: int = 20) -> list[dict]:
      """Search and read records from any Odoo model."""
      return _execute(model, "search_read", domain, fields=fields, limit=limit)

  @mcp.tool()
  def get_model_fields(model: str) -> list[dict]:
      """Return field definitions (name, type, label, required, relation) for an Odoo model."""
      raw = _execute(model, "fields_get", [], attributes=["name","ttype","string","required","relation"])
      result = [{"name":f,"type":d.get("ttype",""),"string":d.get("string",""),
                 "required":d.get("required",False),"relation":d.get("relation","")}
                for f,d in raw.items()]
      return sorted(result, key=lambda x: x["name"])

  @mcp.tool()
  def list_models(keyword: str = "") -> list[dict]:
      """List all installed Odoo models, optionally filtered by keyword."""
      domain = ["|",["model","ilike",keyword],["name","ilike",keyword]] if keyword else []
      return _execute("ir.model","search_read",domain,fields=["id","model","name"],order="model asc",limit=200)

  @mcp.tool()
  def get_record(model: str, record_id: int, fields: list = []) -> dict:
      """Read a single Odoo record by ID."""
      kwargs = {"fields": fields} if fields else {}
      records = _execute(model, "read", [record_id], **kwargs)
      return records[0] if records else {"error": f"No record: {model} id={record_id}"}

  @mcp.tool()
  def execute_method(model: str, method: str, ids: list, kwargs: dict = {}) -> Any:
      """Call any public method on an Odoo model. WARNING: can modify data."""
      return _execute(model, method, ids, **kwargs)

  @mcp.tool()
  def get_odoo_log(lines: int = 50) -> str:
      """Return the last N lines from the Odoo log file (max 500)."""
      log_path = "/home/amir/erpProject/odoo.log"
      lines = max(1, min(lines, 500))
      try:
          with open(log_path, "rb") as fh:
              fh.seek(0, 2)
              size = fh.tell()
              fh.seek(max(0, size - lines * 200))
              content = fh.read().decode("utf-8", errors="replace")
          return "\n".join(content.splitlines()[-lines:])
      except OSError as exc:
          return f"Could not read log: {exc}"

  @mcp.tool()
  def list_custom_modules() -> list[dict]:
      """List modules from custom_addons with their installation state."""
      import os as _os
      path = "/home/amir/erpProject/custom_addons"
      dirs = [d for d in _os.listdir(path)
              if _os.path.isdir(_os.path.join(path,d)) and not d.startswith((".",\"__\"))]
      if not dirs:
          return []
      records = _execute("ir.module.module","search_read",[["name","in",dirs]],
                         fields=["name","shortdesc","state","latest_version"],order="name asc")
      known = {r["name"] for r in records}
      for d in sorted(dirs):
          if d not in known:
              records.append({"name":d,"shortdesc":"(not in ir.module.module)","state":"unknown","latest_version":False})
      return records

  if __name__ == "__main__":
      mcp.run()
  ── END SERVER CODE ──────────────────────────────────────────────────────

<!-- ═══════════════════════════════════════════════════════════════════════
     WIP EVALUATION — Per-Hall Material Cost & Consumable Costing
     Prerequisite: BOM components must have operation_id configured (done via UI)
════════════════════════════════════════════════════════════════════════ -->

[ ] WIP evaluation per hall — material cost attribution using operation_id
    - Each mrp.bom.line now has a "Consuming Operation" column (operation_id).
    - Once configured, per-hall material cost = sum of issuance costs for components
      whose raw_move_id.operation_id matches that hall's work order operation.
    - Update _compute_wip_costs on mrp.production to break down material cost per hall
      instead of the current MO-level total.
    - Update WIP tab in MO form to show per-hall material cost alongside labor cost.
    - Update WIP Dashboard consolidated list accordingly.
    - Files: reema_mrp/models/mrp_production.py, reema_mrp/views/mrp_views.xml

[ ] Operation Consumables configuration (indirect materials like ink, oil, needles)
    - New model: reema.operation.consumable
        operation_id: Many2one mrp.routing.workcenter (the hall)
        product_id: Many2one product.product (e.g. Printing Ink)
        consumption_rate: Float (e.g. 0.002 liters per ball produced)
        uom_id: Many2one uom.uom
    - Configuration screen under Manufacturing → Configuration
    - This links indirect materials to specific halls with a per-ball consumption rate.

[ ] MO costing — add consumable cost based on balls produced × rate
    - When computing WIP or closing an MO, calculate:
        consumable_cost = sum(rate × qty_balls_completed) per operation
    - Add consumable_cost field to mrp.production WIP computation
    - Show in WIP tab and WIP Dashboard alongside material + labor

[ ] Procurement planning — consumable PO suggestion based on production output
    - Period report: sum all batch entries in date range × operation consumable rates
      = total consumable consumed (estimated)
    - Compare against actual consumable issuance records (reema.consumable.transaction)
    - Suggest PO quantities for replenishment based on shortfall
    - Optional: auto-generate draft reema.purchase.order for consumables

[] In batch logs, include a column for PO,
  - Also assign a reference number to Batch log

[] BOM deletion — add stricter constraints
  - Current Odoo built-in only blocks deletion if an MO is actively running (state not in done/cancel)
  - No protection for: completed/cancelled MO history, reema.production.order references, invoices
  - Add @api.ondelete on mrp.bom (inherited in reema_mrp) to block deletion if:
      1. Any mrp.production (regardless of state) references the BOM — preserves full history
      2. Any reema.production.order.line references the BOM via bom_id
  - File to modify: reema_mrp/models/reema_production_order.py (MrpBomReemaExt class)

<!-- ═══════════════════════════════════════════════════════════════════════
     PHASE 1 — Foundation
     Goal: Invoice accepted → MOs appear on Waleed's dashboard with BOM
     pre-filled. Waleed confirms → Ali Shan sees Work Orders per hall.
════════════════════════════════════════════════════════════════════════ -->
[x] Sampling Status buttons flow revision — Completed May 9 2026
  - State reordered: Draft → In Progress → Completed → Sample Approved → Production Ready
  - Ship button only visible from sample_approved or production_ready (not completed)
  - statusbar excludes 'shipped' from main flow bar
  - Files: reema_sampling/models/reema_sampling_blueprint.py,
    reema_sampling/views/reema_sampling_blueprint_views.xml

[x] Create & Edit must be disabled in sampling blueprint — Completed May 9 2026
  - Cancel button renamed "Cancel Sample", restricted to base.group_system
  - Confirmation dialog added with "Go Back" dismiss label
  - Files: reema_sampling/views/reema_sampling_blueprint_views.xml

[x] In sampling BOM must activate when sample status is approved — Completed May 9 2026
  - BOM smart button hidden until state reaches sample_approved or later
  - Files: reema_sampling/views/reema_sampling_blueprint_views.xml

[x] The client field in sample, remove create & Edit — Completed May 9 2026
  - Added options="{'no_create': True, 'no_edit': True}" on client_id field
  - Files: reema_sampling/views/reema_sampling_blueprint_views.xml

[x] Cancel button confusion in sampling — Completed May 9 2026
  - Renamed to "Cancel Sample", admin-only (base.group_system), confirmation with "Go Back"
  - Note: MO cancel button still pending (tracked separately below)
  - Files: reema_sampling/views/reema_sampling_blueprint_views.xml

[x] Fix "Production Order" button on Proforma Invoice — Completed May 11 2026
    - Renamed "Create Production Order" → "Generate PO" (visible only when no PO exists)
    - Added "View PO" button (visible only when PO already exists, calls action_view_production_orders)
    - Smart button in oe_button_box kept for count/navigation
    - File: reema_mrp/views/reema_production_order_views.xml

[x] Change Manufacturing Order reference format — Completed May 11 2026
    - Added noupdate="0" record in reema_mrp/data/ir_sequence_data.xml targeting
      mrp.seq_mrp_production to override prefix from WH/MO/ to MO/%(year)s/ with padding 5.
    - Existing MO numbers unchanged; new MOs will use MO/2026/00001 format.

[x] MO number in Production Order lines — clickable link — Completed May 11 2026
    - Added options="{'no_open': False}" to mo_id field in production lines list.
    - File: reema_mrp/views/reema_production_order_views.xml

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

[ ] Single-click navigation for Blueprint / BOM / MO in PO lines
    - In the Production Order form, the line_ids list uses editable="bottom".
      This forces a 2-click sequence: first click activates the row for editing,
      second click follows the Many2one navigation link. Inherent Odoo behaviour.
    - Fix: add small fa-external-link icon buttons (type="object") next to each
      navigable field. Buttons in editable lists bypass row-activation and fire
      on the first click, so navigation becomes single-click.
    - Add `no_open: True` to sample_id / bom_id / mo_id so the field text is plain
      (no confusing partial-link), and use the dedicated button for navigation.
    - Files to change:
        reema_mrp/models/reema_production_order.py
          → add action_open_sample(), action_open_bom(), action_open_mo()
            to ReemaProductionOrderLine
        reema_mrp/views/reema_production_order_views.xml
          → add no_open:True + fa-external-link button after each of the 3 fields
    - Inline qty editing is preserved (no changes to editable="bottom").
    - Plan file: /home/wsl_amir/.claude/plans/cozy-moseying-crown.md

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
     Goal: Full double-entry accounting wired into production, purchase
     cycle, contractor billing, and bank reconciliation live.
     Design decisions: /home/wsl_amir/.claude/plans/ok-harmonic-lerdorf.md

     KEY DECISIONS (locked):
       - COA: 4-level, individual GL account per vendor AND per customer
       - Costing: AVCO (Average Cost), real-time perpetual valuation
       - Currency: PKR only
       - Fiscal Year: July 1 – June 30
       - Opening Balances: fresh start from cutover date
       - Sales: ~99% export (GST 0%), <1% domestic (GST 17%)
       - Labor cost trigger: contractor BILL confirmation, NOT work order
         completion (supervisors never reliably close WOs/MOs/POs)
       - Purchase flow: 3-way match (PM creates PO with price, storekeeper
         receives qty only, accounting posts vendor bill)
════════════════════════════════════════════════════════════════════════ -->

[x] Phase A.0 — Product Group field on all products — Completed May 7 2026
    - Added product_group Selection field to product.template (in reema_mrp/models/reema_product.py)
    - Groups: Raw Material, Packaging, Semi-Finished Good, Finished Good
    - Field appears on product form (after Internal Category), product list (optional column)
    - Search view: 4 quick filters (one per group) + Group By option
    - sfg_product_id on Work Center form now restricted by domain to SFG products only
    - Indexed for fast filtering across large product lists
    - Files: reema_mrp/models/reema_product.py (new), reema_mrp/models/__init__.py,
      reema_mrp/views/mrp_views.xml

[x] Phase A.1 — reema_accounting module: COA + Taxes + Journals — Completed May 15 2026
    - Created new module: custom_addons/reema_accounting/
    - 44 GL accounts loaded via data/account_account_data.xml (full 4-level COA):
        1000 Assets → Cash/Bank (1111,1112), Trade Receivables control (1120),
          Advances & Receivables (1131-1134), Inventory (1141-1144), Fixed Assets
        2000 Liabilities → Trade Payables control (2110), Contractors Payable control (2120),
          Customer Advances control (2130), GST/WHT/EOBI payables
        3000 Equity → Owner Capital (3100), Retained Earnings (3200)
        4000 Revenue → Sales by product line (4100-4300), Other Income (4900)
        5000 COGS → Raw Material Consumed (5100), Direct Labor by type (5200-5220),
          Factory Overhead (5300-5330)
        6000 Operating Expenses → Salaries, Utilities, Admin, Freight, Bank Charges
    - Control accounts (1120, 2110, 2120, 2130) set reconcile=True
    - Individual vendor/customer accounts assigned per partner via
      property_account_payable_id / property_account_receivable_id
    - 5 taxes loaded via data/account_tax_data.xml:
        GST 17% Sale → Cr 2150 Output GST Payable
        GST 0% Export → zero-rated, no GL impact
        GST 17% Purchase (Input Tax) → Dr 1133 Input GST Receivable
        WHT 4.5% Sale → Dr 1134 WHT Receivable (negative tax, deducted from receivable)
        WHT 4% Purchase → Cr 2160 WHT Payable (negative tax, deducted from payment)
    - 5 journals loaded via data/account_journal_data.xml:
        Sales (SALE), Purchase (PURCH), Bank (BNK), Cash (CSH), General (MISC)
    - Files: custom_addons/reema_accounting/__manifest__.py,
      custom_addons/reema_accounting/__init__.py,
      custom_addons/reema_accounting/data/account_account_data.xml,
      custom_addons/reema_accounting/data/account_tax_data.xml,
      custom_addons/reema_accounting/data/account_journal_data.xml
    - TO INSTALL: Apps → Update Apps List → search "Reema Accounting" → Install

[ ] Phase A.2 — Fiscal Year, Currency & AVCO Configuration (Odoo Settings)
    - Accounting → Configuration → Settings:
        Default Currency: PKR
        Fiscal Year: July 1 – June 30
        Lock Date: set after opening entries are posted
    - Inventory → Configuration → Product Categories → create/update:
        "Raw Materials": Cost Method = Average Cost (AVCO),
          Valuation = Automated (Real-time),
          Stock Input Account = 1141, Stock Output Account = 5100,
          Stock Valuation Account = 1141
        "Consumables": Cost Method = AVCO, Valuation = Automated,
          Stock Input = 1144, Stock Output = 5320, Valuation = 1144
        "Finished Goods": Cost Method = AVCO, Valuation = Automated,
          Stock Input = 1143, Stock Output = 5100, Valuation = 1143
        "WIP": Stock Valuation Account = 1142
    - Assign all existing products to their correct category
    - Result: goods receipt auto-posts Dr Raw Materials / Cr GRNI;
      material issuance auto-posts Dr WIP / Cr Raw Materials;
      MO close auto-posts Dr Finished Goods / Cr WIP (no code needed)

[ ] Phase A.3 — Contractor Bill Model + Workflow
    - New model: reema.contractor.bill in reema_mrp/models/reema_contractor_bill.py
    - Purpose: labor cost hits COGS only when contractor bill is confirmed,
      NOT when work order is completed (supervisors don't close WOs reliably)
    - Bill is fully independent of WO/MO/PO closure state
    - Fields: contractor_id, work_type (stitching/cutting/sublimation),
      date, line_ids, state, account_move_id, total_amount
    - Bill lines: description, qty (from contractor tally), piece_rate_id,
      rate (auto-filled from piece rate master, editable), subtotal
    - Workflow states:
        draft → [Supervisor Approves qty against physical count]
        supervisor_approved → [Accounting Confirms]
        confirmed → posts account.move:
                      Dr 5200/5210/5220 Direct Labor (by work_type)
                      Cr 2121/2122/2123 Contractor Payable (by contractor)
        paid → [Register Payment] Dr Contractor Payable / Cr 1111 Bank
    - Payment is often instant (same session as confirmation)
    - Files to create: reema_mrp/models/reema_contractor_bill.py (new),
      reema_mrp/views/reema_contractor_bill_views.xml (new)
    - Files to modify: reema_mrp/models/__init__.py, reema_mrp/__manifest__.py

[ ] Phase A.4 — Sales Invoice from Pro Forma Invoice
    - reema.invoice (PI) is currently a standalone document with no accounting impact
    - When PI is marked as Shipped (action_mark_shipped), auto-generate account.move
    - New field on reema.invoice: account_invoice_id (Many2one account.move, readonly)
    - Override action_mark_shipped(): create account.move (move_type='out_invoice')
        Partner: partner_id → uses partner's property_account_receivable_id
        Lines: from reema.invoice.line → product + qty + price_unit
        Tax: GST 0% Export by default; GST 17% if is_domestic=True on invoice
        Journal: Sales (SALE)
        Link: account_invoice_id ← new move
    - Add smart button on PI form: "Accounting Invoice" (links to account.move)
    - Files: custom_addons/reema_invoice/models/reema_invoice.py

[ ] Phase A.5 — Purchase & Vendor Bills Setup (Native Odoo, config only)
    - No custom code needed — use Odoo's standard purchase module
    - 3-way match flow:
        1. Production Manager creates PO (product + qty + agreed price)
        2. Storekeeper validates receipt (qty only — price comes from PO automatically)
           AVCO updates and journal entry posted (handled by Phase A.2 config)
        3. Accounting creates vendor bill from PO (price + qty already filled)
           Dr GRNI clearing / Cr vendor's individual account (2111, 2112...)
           Input GST and WHT taxes applied
    - Configuration required:
        Each vendor partner: set property_account_payable_id → their individual account
        Each customer partner: set property_account_receivable_id → their individual account
        WHT and Input GST taxes set as default on vendor records

[ ] Phase A.6 — Payments & Advances
    - Customer Advances:
        account.payment inbound → post to customer's advance account (2131/2132...)
        On invoice confirmation, reconcile advance against receivable
    - Supplier Advances:
        account.payment outbound → post to 1131 Advances to Suppliers
        On vendor bill confirmation, reconcile advance against payable
    - Contractor instant payment: built into Phase A.3 contractor bill flow
    - Test: advance paid → invoice raised → reconcile → balance = 0

[ ] Phase A.7 — Bank & Reconciliation
    - Use native Odoo account.bank.statement
    - Manual entry of bank statement lines weekly
    - Reconcile against: customer payments, vendor payments, contractor payments
    - Bank charges: Dr 6600 Bank Charges / Cr 1111 Bank (manual journal entry)
    - Verify: bank GL account balance = physical bank statement balance

[ ] Phase A.8 — Opening Balance Entry (one-time, on go-live date)
    - Post one journal entry via Misc (MISC) journal on the cutover date:
        Dr 1111 Main Bank Account → actual bank balance
        Dr 1121/1122... Trade Receivables → per customer outstanding
        Dr 1141 Raw Materials → physical count × AVCO unit cost
        Dr 1143 Finished Goods → physical count × AVCO unit cost
        Cr 2111/2112... Trade Payables → per vendor outstanding
        Cr 2131/2132... Customer Advances → per customer advance held
        Cr/Dr 3100 Owner Capital → balancing figure
    - Lock all dates before go-live: Accounting → Settings → Lock Date
    - Train each staff role on their specific screens before go-live


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

[x] Batch Log view + Piece Rate linkage on batch entries — Completed May 13 2026
    - Added `piece_rate_id` (Many2one → reema.piece.rate) and `amount_earned`
      (computed: rate × qty, stored) to `reema.wo.batch.entry`.
    - Wizard: `workcenter_id` related field added so piece rate dropdown filters to
      only rates configured for the current hall's work center.
    - New standalone list/form/search view for all batch entries:
        Columns: Date, Logged By, Contractor, Work Order, Qty, Balls, Piece Rate, Amount (PKR, summed)
        Search: by Logged By, Contractor, Work Order, Piece Rate; filters: Today, This Month
        Group by: Logged By, Contractor, Work Order, Date (month)
    - Menu: Manufacturing → Batch Logs (sequence 25)
    - Smart button on res.partner contact form: shows batch entry count for that user;
      visible only when count > 0; filtered by logged_by.partner_id
    - Files:
        reema_mrp/models/reema_wo_batch.py
        reema_mrp/models/res_partner.py (new)
        reema_mrp/models/__init__.py
        reema_mrp/views/reema_wo_batch_views.xml

[ ] Piece Rate system — design decisions pending (discuss before building further)

    WHAT IS BUILT:
    - reema.piece.rate config table: Work Center + Type of Work + Rate (PKR) + UOM
      Location: Manufacturing → Configuration → Piece Rates
    - Supervisor optionally picks a piece rate when logging a batch (filtered to that hall)
    - amount_earned = rate × qty is stored on the batch entry
    - Batch Logs view shows PKR per entry with a column total

    OPEN DECISIONS (resolve before Phase 2.3):

    1. MO column in Batch Logs list
       - Currently shows Work Order name (e.g. "Cutting") but NOT MO number (MO/2026/00012)
       - Add production_id as a separate column for quick MO identification

    2. Piece rate population
       - Who enters rates — Waleed or Irfan?
       - How many work types per hall? (e.g. Cutting Plain vs Cutting Printed)
       - Same rate for all contractors, or negotiated individually per contractor?
       - Current design: one rate per hall + work_type, same for everyone

    3. Payables generation (Phase 2.3)
       - amount_earned exists on batch entries but is NOT posted to accounting yet
       - Irfan needs weekly payables report per contractor
       - Decision: use account.move (vendor bill) or a custom payable model?

    4. Approval workflow
       - Should Irfan approve batch entries before amounts are finalized?
       - Or is a saved batch entry final?

    Files to modify when resolved:
        reema_mrp/models/reema_wo_batch.py
        reema_mrp/models/reema_piece_rate.py
        reema_mrp/views/reema_wo_batch_views.xml

[ ] Phase 2.3 — Piece rate payables to accounting
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

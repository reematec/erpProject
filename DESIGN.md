# Reema Group — Full Odoo System Design

## Context
Reema Group (football manufacturer) is adopting Odoo as their complete business system
covering manufacturing, inventory, purchasing, accounting, and finance. The goal is to
eliminate management irregularities: unrecorded stock movements, lack of accountability,
delays, and lack of enforced decision chains. This document is the master design reference
before any configuration begins.

---

## Confirmed Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Fiscal Year | Jul 1 – Jun 30 | Pakistan standard |
| Go-Live | TBD (months away) | Still in development |
| Base Currency | PKR only | All transactions recorded in PKR |
| Foreign Currencies | None in Odoo | Conversion done externally at bank rate; PKR amount entered into Odoo |
| Stock Valuation | AVCO (Average Cost) | Buy-per-order pattern, no large batches |
| Warehouse | Single warehouse, sub-locations per hall | Each hall holds its own WIP/SFG |
| Sales Type | Exports only | Zero-rated GST |
| GST | Registered | Zero-rated on all sales |
| Withholding Tax | Yes — on supplier payments (where allowed) | Some suppliers refuse deduction |
| Bank Accounts | 2–3 accounts | PKR current + export receipts account |
| Accountant | In-house | Will manage CoA and filings |
| Opening Data | Start fresh | Opening balances only on go-live date |

---

## Modules to Enable

```
Accounting (full)       — replaces basic Invoicing, gives double-entry, bank reconciliation
Purchase                — supplier POs, goods receipts, vendor bills, payments
Inventory               — already partial, needs location structure
Manufacturing (MRP)     — already installed, in active development
Pakistan Localization   — l10n_pk: standard CoA + tax configuration
Payroll                 — future phase (permanent staff salaries)
```

---

## Warehouse Location Structure

```
Reema Warehouse
├── Raw Material Store          ← all incoming materials received here
├── Production Halls (virtual parent)
│   ├── Lamination Hall
│   ├── Cutting Hall
│   ├── Printing Hall
│   ├── Stitching Hall
│   └── ... (all 17 halls — WIP/SFG lives here)
├── Finished Goods Store        ← completed footballs ready for export
└── Packing Area                ← optional, for packing before dispatch
```

Each MO moves material: Raw Material Store → Hall (consumption) → next Hall (SFG transfer)

---

## Tax Configuration

### Sales (Outgoing Invoices)
- All sales = exports → **0% GST (zero-rated)**
- No tax collected from customers

### Purchases (Incoming Bills)
- Input GST on local purchases where applicable
- **Withholding Tax (Section 153 Income Tax)**:
  - Filer suppliers: 4.5%
  - Non-filer suppliers: 9%
  - Per-supplier flag: `withholding_allowed = True/False`
  - If False → full payment, WHT not deducted (supplier's condition)

---

## User Roles & Access Design

| Role | Key Permissions |
|---|---|
| **Owner** | Full read access everywhere, approve large payments |
| **Admin (Waleed)** | Full operational access, all modules |
| **Production Manager** | Manufacturing: full. Inventory: read-only. No accounting. |
| **Store Keeper** | Inventory: receive + issue. Purchase: confirm receipt. No payments. |
| **Accountant** | Full accounting. Vendor bills. Payments. No stock operations. |
| **Sales** | Pro forma invoices + production orders. No accounting. |
| **Packing** | Delivery orders only |
| **Supervisor** | Work orders for their hall only |
| **Designer** | Sampling module only |
| **Sampling Incharge** | Sampling + blueprint management |
| **Gate** | Incoming/outgoing delivery confirmation only |
| **HR** | HR module (future phase) |

**Key separation of duties:**
- Store Keeper can receive stock but cannot pay suppliers
- Accountant can pay but cannot move physical stock
- Production Manager cannot modify invoices or payments

---

## Controls for Irregularities

### Problem: Materials leaving store unrecorded
**Solution:** Work orders are hard-blocked from starting unless the Store Keeper has
validated the material transfer in Odoo. This creates an unavoidable conflict when
material is issued physically but not entered — the hall supervisor gets blocked,
escalates to production manager, who traces it back to the store keeper.

**Implementation:** Extend the existing `button_start` override on `mrp.workorder`
(file: `reema_mrp/models/reema_production_order.py`) with a second check:
- Block if ALL component moves for this MO are unvalidated (nothing issued at all)
- Allow if at least one component move is validated (partial issue is acceptable —
  halls process available quantity, hold the rest)
- Error message names the MO and directs supervisor to the Store Keeper

**Enforcement chain:**
```
Store Keeper skips entry → Transfer not validated
→ Hall Supervisor clicks Start → BLOCKED with clear message
→ Escalates to Production Manager → traces to Store Keeper
→ Store Keeper forced to validate → Work order unblocks
```

**Important:** Standard Odoo does NOT hard-block on this — this requires a custom check.

### Problem: Stock discrepancies
**Solution:**
- Periodic inventory counts via Odoo Physical Inventory feature
- Each hall's WIP tracked as a named location
- Discrepancies flagged as inventory adjustments with mandatory reason

### Problem: Decision enforcement / accountability
**Solution:**
- Every document has a chatter log (who did what, when)
- State-based workflow: Draft → Confirmed → Done — no skipping states
- Role-based locks: only authorized roles can confirm/validate each document type

### Problem: Supplier payment without verification
**Solution:** 3-way match enforced:
```
Purchase Order (approved) → Goods Receipt → Vendor Bill → Payment
```
Payment cannot be registered without a matched bill. Bill cannot be created without a receipt.

---

## Procurement Flow (Purchase → Inventory → Accounting)

```
1. Create Purchase Order   (Admin / Production Manager)
   └── Supplier, material, qty, rate, delivery date

2. Receive Materials       (Store Keeper)
   └── Validates PO qty vs actual received
   └── Stock enters: Raw Material Store
   └── AVCO cost updated automatically

3. Vendor Bill created     (Accountant)
   └── Auto-populated from PO
   └── WHT deducted if supplier allows
   └── Journal entry: Dr Inventory / Cr Accounts Payable

4. Payment                 (Accountant)
   └── Bank payment registered
   └── Journal entry: Dr Accounts Payable / Cr Bank
   └── Bank reconciliation matches statement
```

---

## Sales / Export Flow

```
1. Pro Forma Invoice        (Sales) — already built
   └── Customer, items, qty, rate in PKR

2. Production Order         (Admin/Production Manager) — already built
   └── Linked to Pro Forma Invoice
   └── MOs created per BOM

3. Manufacturing            (Production Manager / Supervisors)
   └── Work orders through 17 halls
   └── Material consumed from RM Store
   └── SFG moves between halls

4. Finished Goods           (Store Keeper)
   └── MO completed → FG enters Finished Goods Store

5. Delivery / Export        (Gate / Packing)
   └── Delivery Order created
   └── Stock leaves FG Store

6. Export Invoice           (Accountant)
   └── In PKR (USD/EUR/GBP rate applied externally before entry)
   └── Journal entry: Dr Accounts Receivable / Cr Sales Revenue

7. Customer Payment         (Accountant)
   └── PKR received in bank account
   └── Payment registered in PKR — no currency conversion in Odoo
```

---

## How Inventory & Manufacturing Integrate

When an MO runs, stock movements and accounting entries happen automatically:

```
Raw Material Store → Hall (material issued) → WIP → Finished Goods Store
     ↓                        ↓                          ↓
Dr WIP / Cr RM Inventory    (auto journal)        Dr FG / Cr WIP
```

Work order start is hard-blocked until:
1. Store Keeper has validated the material transfer (at least partial)
2. Contractor is assigned to the work order

---

## How Purchases & Payments Integrate with Accounting

```
Step              System Action                      Journal Entry
────              ─────────────                      ─────────────
PO created        Commitment document only            None
Goods received    Stock increases in RM Store         Dr RM Inventory / Cr GR Clearing
Bill matched      GR Clearing cleared                 Dr GR Clearing / Cr Accounts Payable
                                                      Cr WHT Payable (if applicable)
Payment made      Payable cleared                     Dr Accounts Payable / Cr Bank
```

All entries are automatic. Accountant reviews and reconciles, not manually posts.

---

## Payment & Cash Design

### Journals Required
| Journal | Type | Purpose |
|---|---|---|
| Bank — PKR Current | Bank | Main supplier/customer payments |
| Bank — (2nd account) | Bank | Secondary bank account |
| Petty Cash | Cash | Day-to-day cash expenses (significant volume) |
| Contractor Cash | Cash | Cash contractor piece-rate payments |

### Advance Payments
Both directions are in use and need dedicated accounts in CoA:
- **Advance to Supplier** (Asset): Paid before delivery → cleared when goods received and bill matched
- **Advance from Customer** (Liability): Received before production → cleared when invoice raised and delivery done

Workflow for supplier advance:
```
Pay advance    → Dr Supplier Advance (asset) / Cr Bank
Receive + bill → Dr RM Inventory / Cr Accounts Payable
Match advance  → Dr Accounts Payable / Cr Supplier Advance
Pay balance    → Dr Accounts Payable / Cr Bank
```

### Contractor Payments
- Piece-rate amounts computed per work order (already in MRP module)
- Payment method: cash or bank transfer depending on contractor
- Journal entry at payment: Dr Labor Cost / Cr Cash or Bank
- Accumulated per contractor — periodic settlement

### Payment Recording (Key Point)
Current state: approvals already happen informally and controls exist.
Gap: transactions are not entered into any system.
Odoo's role: **recording** existing approved transactions, not adding new approval gates.

---

## Chart of Accounts (Pakistan Localization)

Install `l10n_pk` — provides Pakistan-standard CoA. In-house accountant reviews and
adjusts account names/codes to match Reema's existing books before go-live.

Key accounts to verify with accountant:
- Raw Material Inventory
- WIP / Semi-finished Goods (per hall or single WIP account)
- Finished Goods
- Cost of Goods Sold
- Export Sales (zero-rated)
- Accounts Payable (local suppliers)
- **Supplier Advances** (asset — advance payments made before delivery)
- **Customer Advances** (liability — deposits received before production)
- WHT Payable
- Labor Cost (contractor piece-rate)
- Bank accounts (PKR)
- Petty Cash
- Contractor Cash

---

## Go-Live Checklist (Opening Balances Day)

On the agreed go-live date, before first live transaction:
1. Enter raw material stock quantities + unit cost (AVCO starting value)
2. Enter cash/petty cash balances
3. Enter bank balances per account
4. Enter outstanding supplier payables (what Reema owes suppliers)
5. Enter outstanding customer receivables (what customers owe Reema)
6. Lock all accounting periods before go-live date (prevent back-dating)

---

## Implementation Phases

### Phase A — Foundation
Configuration work. No custom code.
- A.1  Install Accounting + Purchase + Pakistan localization (`l10n_pk`)
- A.2  Fiscal year (Jul–Jun) + PKR as sole currency
- A.3  Chart of Accounts review with in-house accountant
- A.4  Tax config: zero-rated exports, WHT supplier flags
- A.5  Journals: 2–3 bank accounts + petty cash + contractor cash
- A.6  Warehouse sub-locations: RM Store, 17 halls, FG Store
- A.7  Product categories: Raw Materials (AVCO), Finished Goods (AVCO)
- A.8  User roles + access rights (all ~10 roles)

### Phase B — Procurement
- B.1  Supplier master data (name, NTN, WHT flag, bank details)
- B.2  Raw material products + units of measure
- B.3  Purchase flow: PO → Receipt → Bill → Payment walkthrough
- B.4  3-way match verification

### Phase C — Manufacturing (in progress — see task.md Phase 1/2/3)
- C.1  17 work centers finalized
- C.2  SFG stock movement on work order completion (Phase 1.5)
- C.3  Material issuance block on work order start (custom code — Phase 1.5e)
- C.4  FG stock entry when MO marked done

### Phase D — Sales & Export
- D.1  Delivery Order linked to Pro Forma Invoice
- D.2  Export invoice (PKR) linked to delivery
- D.3  Customer payment recording + bank reconciliation

### Phase E — Controls & Compliance
- E.1  Physical inventory workflow
- E.2  Opening balance entry
- E.3  Period locking + user training

### Phase F — Reporting
- F.1  Cost per order (material + labor)
- F.2  Production efficiency by hall
- F.3  Financial statements: P&L, Balance Sheet, Cash Flow
- F.4  Supplier payment aging
- F.5  WHT summary for FBR filing
- F.6  Advance payment tracking (outstanding supplier advances, customer deposits)

### Phase G — Payroll (future)
- G.1  Install Payroll module
- G.2  Employee contracts and salary structures
- G.3  Monthly payroll runs → journal entry posted to accounting

---

## Key Risks to Watch

| Risk | Mitigation |
|---|---|
| WHT non-compliance for supplier refusing deduction | Flag supplier, document reason, accountant files correct return |
| Stock AVCO distorted by wrong receipt costs | Store keeper must verify rate on each receipt against PO before validating |
| Mid-year go-live complexity | Strongly recommend Jul 1, 2026 go-live — cleanest fiscal year start |
| Advance payments not cleared | Monthly review of Supplier Advances and Customer Advances accounts |

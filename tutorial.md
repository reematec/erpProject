# Tutorial: Testing "Reema Logic" in Standard Odoo 18

Welcome to your first Odoo testing session. This tutorial will guide you through the **Hybrid (HYB) Football** production process using the baseline setup we just created. 

The goal is to perform the actual factory steps so you can see where Odoo works perfectly and where we need to build our custom "Reema Logic."

---

## Phase 1: Preparation & Login
1. **Start the Server:**
   In your terminal, run:
   ```bash
   ./odoo-venv/bin/python3 odoo/odoo-bin -c odoo.conf --dev=all
   ```
2. **Open the Browser:** Go to `http://localhost:8069`
3. **Login:** 
   - Use **`waleed`** (Production Manager) to plan and confirm orders.
   - Use **`alishan`** (Production Assistant) to record actual floor work.
   - *Passwords are in `credential.md` (usually role name + 123, e.g., `waleed123`).*

---

## Phase 2: The Physical Flow (Ali Shan's Role)
Navigate to the **Manufacturing** app. You will see three Manufacturing Orders (MOs) waiting for you.

### Step 1: Lamination (Hall 2)
1. Open **MO WH/MO/00001** (Laminated Sheet).
2. Click the **Work Orders** tab.
3. Click **Start** on the "Lamination" operation.
4. After a few seconds, click **Done**.
5. **Observe:** The "Laminated Sheet" is now in stock. Odoo automatically marks the next MO (Printed Panel Set) as "Ready" because the materials are now available.

### Step 2: Cutting & Printing (Halls 3 & 4)
1. Open **MO WH/MO/00002** (Printed Panel Set).
2. Go to **Work Orders**.
3. **Start/Done** the "Cutting" operation.
4. **Start/Done** the "Printing" operation.
5. **Observe:** You have now produced "Printed Panel Sets."

### Step 3: Assembly (Halls 6 to 17)
1. Open the final MO **WH/MO/00003** (HYB Football).
2. This is the long chain. Walk through the Work Orders one by one:
   - **Stitching** (Hall 6)
   - **Foam Attachment** (Hall 7)
   - **Turning** (Hall 8)
   - ... and so on.

---

## Phase 3: The "Gap Analysis" (What's Missing?)
As you perform the steps above, try to find these "Reema Logic" features. **Spoiler: You won't find them because Odoo doesn't have them yet!**

### 1. Where is the Contractor?
- **Task:** Try to record that **Ali Mohsin** did the stitching and **Bahadar Shah** did the turning.
- **Problem:** Odoo only records that the "Work Center" did it. There is no way to select a specific person/contractor to ensure they get paid.

### 2. Where is the Piece-Rate Payment?
- **Task:** Look for a report showing how much money is owed to the Stitching contractor for those 100 balls.
- **Problem:** Odoo's "Cost Analysis" only shows the machine's hourly cost (which we set to 0). It does not calculate "100 balls x Rs. X per ball."

### 3. The Rework Loop
- **Task:** Imagine a ball fails **Initial QC (Hall 13)**. Try to send it back to **Closing (Hall 10)** for repair.
- **Problem:** In standard Odoo, if you click "Done" on QC, it moves forward to Shaping. There is no easy "Rework" button that sends the inventory backward in the sequence.

### 4. Consumable Guesswork
- **Task:** Look at the **Latex** or **Ink** inventory. 
- **Problem:** Odoo "consumed" exactly what was on the BoM. If you used slightly more or less on the floor, the system doesn't flag the "Variance" unless you manually adjust it.

---

## Phase 4: Financial Review (Irfan's Role)
1. Login as **`irfan`**.
2. Go to **Manufacturing -> Reporting -> Cost Analysis**.
3. Open the report for the HYB Football.
4. **The Big Discovery:** Notice that the **Labor Cost is $0**. This is the biggest gap we will bridge with our custom code.

---

## Summary for the Developer (CLI)
Once you have finished this tutorial, we will have a clear list of what to build:
1. **Contractor Assignment:** A way for Ali Shan to pick a name at each Hall.
2. **Piece-Rate Engine:** A system that turns "Done" work into a "Payable" for the contractor.
3. **Quality Buttons:** "Pass", "Rework", and "Reject" buttons with real inventory logic.

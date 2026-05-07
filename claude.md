Reema Group: Ball Constructions Types
One must first understand the four distinct ways we construct a football. While they all start with the same raw materials (PU, Fabric, Foam, Latex), their "Core Assembly" is fundamentally different.
1. Hand Stitched (HS) – The ILO-Compliant Path
•	The Difference: Due to social compliance and the elimination of child labor, all Hand Stitched balls are processed outside the main factory by contractors registered with the ILO.
•	System Requirement (Issue & Receive): * ERP System must track the Issue of "Printed Panel Sets" and "Bladders" to specific ILO-registered contractors.
o	ERP System must track the Receive of the finished "Stitched Shell" back into the Reema Group facility.
•	Assembly: Panels are joined manually using high-tensile thread. The bladder is glued to a panel before stitching starts.
•	Key Logic: Bypasses Turning and Closing halls. Once received back from the contractor, the ball goes straight to Initial QC.
2. Machine Stitched (MS) – In-House Path
•	Assembly: Panels are joined via industrial sewing machines inside the Reema Group facility.
•	Logic: The ball is stitched inside-out (Shell).
•	Key Path: Requires the Turning Hall, Bladder Attachment Hall, and Closing Hall (hand-stitching the final small opening).
3. Machine Stitched Hybrid (HYB) – In-House Path
•	Assembly: Stitched by machine to create an inside-out shell.
•	The "Foam Layer" Difference: Before the shell is turned, a foam panel is attached to the interior of the shell using latex.
•	Sequence: Stitching -> Foam Attachment (Internal) -> Turning -> Bladder Attachment -> Closing.
•	Note: This adds a specific material (Foam) and a labor step (Latex attachment) to the BoM compared to the MS ball.
4. Thermo Bonded (THB) – In-House Path
•	Assembly: Stitchless construction using heat-activated adhesive.
•	Logic: The bladder is reinforced in the Binding Hall.
•	Key Path: Fabric Patched bladder and panels are fused in a pressurized heat mold in the THB Hall. Bypasses all stitching, turning, and closing halls. However it has its own processes like, PU Panel and Foam Gluing, Panel Edge Turning, Gluing Turned Edges, Joining Glued Panels, Preparing Bladder by wrapping fabric patch around bladder with latex, infusing joined halfs with bladder

Construction Comparison 
Construction	Hand Stitched (HS)	Machine Stitched (MS)	Hybrid (HYB)	Thermo Bonded (THB)
Location	Outsourced (ILO)	In-House	In-House	In-House
Joining Method	Hand Stitch	Machine Stitch	Machine Stitch	Heat Fusion (Glue)
Internal Layer	Standard Backing	Standard Backing	Foam Panel + Latex	Fabric-Patched Carcass
Turning Required	No	Yes	Yes	No
Bladder Logic	Attached to Panel first	Inserted after Turning	Inserted after Turning	Infused inside Mold
Closing Hall	No	Yes	Yes	No
Molding Process	No	No (Shaping only)	Optional (Shaping)	High-Pressure Heat Mold
________________________________________





Reema Group: Process & Hall Master List

Process / Hall	Description of Operation	Construction Type (Who goes through this?)
1. Raw Material Store	Storage of PU rolls, fabric, bladders, chemicals, and thread.	ALL (HS, MS, HYB, THB)
2. Lamination	Joining PU leather with backing fabric using latex/glue.	ALL (HS, MS, HYB, THB)
3. Cutting	Cutting laminated sheets into specific panel shapes (32, 14, 6 panels).	ALL (HS, MS, HYB, THB)
4. Printing	Screen or machine printing of logos, designs, and technical specs.	ALL (HS, MS, HYB, THB)
5. ILO External Issue	Logistics point where panels are issued to outside contractors.	HS Only
6. Stitching (In-House)	Machine stitching of the panels into an inside-out shell.	MS & HYB
7. Foam Attachment	Applying latex and foam panels to the inside of the stitched shell.	HYB Only
8. Turning	Flipping the machine-stitched shell to be right-side out.	MS & HYB
9. Bladder Attachment	Inserting and securing the bladder into the shell.	MS & HYB
10. Closing	Hand-stitching the final opening of the MS/HYB ball.	MS & HYB
11. THB Binding	PU Panel and Foam Gluing with latex, Panel Edge Turning, Gluing Turned Edges, Joining Glued Panels, Preparing Bladder by wrapping fabric patches around bladder with latex and drying, 	THB Only
12. THB Molding	Fusing panels to the bladder in a high-pressure heat mold.	THB Only
13. Initial QC	First inspection for weight, shape, and stitching/bonding errors.	ALL (HS, MS, HYB, THB)
14. Shaping	Placing balls in a shaping machine to ensure perfect roundness.	ALL (HS, MS, HYB, THB)
15. Cleaning & Sealing	Removing stains and applying optional waterproof seam sealant.	ALL (MS/HYB/THB mostly)
16. Final QC	Final air-leak test (24-hour test) and visual grading.	ALL (HS, MS, HYB, THB)
17. Packing & FG Store	Deflation, bagging, and moving to Finished Goods (FG) Store.	ALL (HS, MS, HYB, THB)
________________________________________





Reema Group: Unit Conversion & Transformation Map
Must define the Unit of Measure (UoM) Conversion at each step. In a football, the product "morphs" from area to area—starting as a roll of material and ending as a single ball.
If doesn't handle these conversions, inventory levels will be wrong. Here is the breakdown of how the units change at each Work Center.

#	Work Center (Hall)	Input Unit (What goes in)	Output Unit (What comes out)	Conversion Logic
1	Raw Store	Meters / KG / Rolls	Meters / KG	Base storage of raw materials.
2	Lamination	Meters (PU + Fabric)	Sheets	1 Meter of PU + 1 Meter of Fabric = 1 Laminated Sheet.
3	Cutting	Sheets	Panel Sets	1 Sheet = X Sets (e.g., 1 sheet yields 4 sets of 32 panels).
4	Printing	Panel Sets	Printed Sets	Units remain "Sets," but value increases (Added Cost).
5	ILO Issue (HS)	Printed Sets + Bladders	Issued Batch	Tracking "Sets" leaving the factory gates.
6	Stitching (In-House)	Printed Sets	Stitched Shells	Transformation from flat panels to a 3D Ball/Shell.
7	Foam Attach (HYB)	Stitched Shells + Foam	Hybrid Shells	Adding foam layers to the existing shell unit.
8	Turning	Inverted Shells	Right-side Shells	Physical change only; unit remains 1 Ball.
9	Bladder Attach.	Shells + Bladders	Shells with Bladder	Consumption of 1 Bladder per 1 Shell.
10	Closing	Open Shells	Closed Balls	The first time the unit is a "Complete Ball."
11	THB Binding	Bladders + Thread	Carcasses	1 Bladder becomes 1 Carcass.
12	THB Molding	Printed Sets + Carcass	Molded Balls	Heat fusion of panels and carcass into 1 Ball.
13-16	QC / Shaping / Clean	Balls	Verified Balls	No change in unit; value increases with labor.
17	Packing	Balls + Polybags + Cartons	Export Cartons	X Balls = 1 Carton (e.g., 50 balls per carton).
________________________________________
Key Rules for the ERP System Team
1. The "Yield" Calculation (Meters to Sets)
The most critical conversion is between Hall 2 (Lamination) and Hall 3 (Cutting).
•	The system must track how many Panel Sets (Output) were produced from a specific number of Laminated Sheets (Input).
•	Any gap here represents Scrap/Waste, wrong average or material theft.
2. The Component Consumption (BoM)
ERP System must understand that at Hall 9 (Bladder Attachment) or Hall 11 (Binding), the system must "deduct" one Bladder from the Raw Store for every one Ball moving through the hall.
3. The "Subcontracting" Unit (Hall 5)
For Hand Stitched (HS) balls, the conversion happens outside.
•	Input to Contractor: 100 Printed Sets + 100 Bladders.
•	Output from Contractor: 100 Stitched Shells.
•	The system must show 100 sets "In-Transit" until the contractor returns them as shells.


System Operators (The Data Entries)
These individuals will have ERP System logins. They are responsible for recording the movement of material from one hall to the next.
Operator Name	Role in ERP System	Responsibility
Management	System Admin	Oversight of all departments, financial approvals, and master reports.
Waleed	Production Manager	Creating Manufacturing Orders (MOs) and scheduling which construction runs in which hall.
Ali Shan	Production Assistant	The most active user. He records the "Move" from Hall to Hall and tags which contractor did the work.
Sameer Mehmood	Sales & Shipping	Entering client orders and managing the export/packing lists.
Irfan	Accountant	Validating contractor work to generate "Vendor Bills" (Payables) and managing raw material costs.
Gatekeeper	Gate Security	Recording the "Issue" and "Receive" of Hand Stitched (HS) material to ILO contractors.
The Contractors (The Payees)
These people do not log into the system. Instead, they are created as "Vendors". When Ali Shan records that 100 balls were stitched, the system automatically calculates how much is owed to these individuals.
Contractor Name	Assigned Hall / Process	Payment Basis (Piece-Rate)
Mushtaq	Lamination	per Meter / Sheet
Afzal	Cutting	per Ball Set
Amir / Shamas	Printing	per Impression / Set
Ali Mohsin	Stitching (In-House)	per Stitched Shell
Ihtesham Ali	THB Hall (Molding)	per Molded Ball
Imran	Binding (THB Carcass)	per Carcass
Bahadar Shah	Turning	per Ball
Manazar Shah	Bladder & Closing	per Ball
Waseem	Seam Sealing	per Ball
Tahir Abbas	Cleaning	per Ball
ILO Contractors	External Stitching (HS)	per Received Shell

3. The "Work-to-Pay" Logic 
The Implementation team needs to understand the relationship between the Operator and the Contractor:
1.	The Trigger: Ali Shan (Operator) goes to the Stitching Hall.
2.	The Action: He records that Ali Mohsin (Contractor) has finished 200 MS Shells.
3.	The Result: System moves the inventory from "Stitching Hall" to "Turning Hall" AND it creates a pending credit for Ali Mohsin for 200 units at his specific rate.
4.	The Audit: Irfan (Accountant) reviews these entries at the end of the week, upon and after approval from Waleed (System must develop an approval system), clicks "Post" to finalize the contractor's payment.
________________________________________
4. The Gatekeeper & ILO Contractors
For Reema Group’s Hand Stitched balls, the Gatekeeper is the system operator.
•	When the ILO Contractor arrives, the Gatekeeper scans the material out.
•	When the Contractor returns the stitched shells, the Gatekeeper scans them in.
•	This "Receive" action is what tells the system the contractor has earned their piece-rate payment.
________________________________________




QC & Rejection Logic
1. The Three QC Outcomes
When a ball reaches Hall 13 (Initial QC) or Hall 16 (Final QC), the operator (Ali Shan or a QC Inspector) must have three buttons in the System:
A. Pass (The Standard Flow)
•	Action: Ball moves to the next Hall (e.g., Shaping or Packing).
•	Payment: Contractor who completed the previous stage (e.g., Stitching) is cleared for payment.
B. Rework (The Repair Loop)
•	Context: The ball has a minor issue (e.g., loose thread, poor cleaning, minor seam gap).
•	Action: The ball is sent back to a previous Work Center (e.g., Closing or Cleaning).
•	System Logic: The System must flag this ball so the contractor is not paid a second time for fixing their own mistake.
•	System must track how many balls were sent back 
o	Inventory stays in "WIP" but moves backward in the sequence.
C. Reject (B-Grade or Scrap)
•	Context: Major defect (e.g., PU tear, improper lamination, weight out of spec).
•	System Action: * The ball is moved out of the "A-Grade" production line.
o	It is transferred to the "B-Grade Warehouse" (to be sold at a discount) or the "Scrap Location" (to be destroyed).
o	The System must record the reason for rejection (e.g., "Lamination Issue" or "Stitching Error") for monthly quality reports.
________________________________________








Wastage & Scrap Cost Calculation
1. Standard Waste Factor (The Buffer)
Every Bill of Materials (BoM) should have a built-in Wastage Percentage.
•	Example: If a ball physically uses 0.25 meters of PU, we set the BoM to consume 0.28 meters.
•	The Result: The System automatically prices the ball based on the "Gross" material needed to produce it, covering the standard scrap from cutting.
2. Order-Specific Scrap (The Actuals)
Sometimes, a specific batch has more waste (e.g., a bad PU roll or a new cutter).
•	The Process: When Afzal finishes cutting a batch of 1,000 balls, the System compares the actual PU issued to the actual sets produced.
•	The Proposal: The ERP should "Variance Post" the extra waste directly to that Manufacturing Order.
•	Why? This ensures that if an order was particularly wasteful, the Product Cost Report for that specific client shows a lower margin.
3. QC Rejection Costing
When a ball is scrapped in Final QC, the cost of the raw materials and all the piece-rates already paid (Lamination + Cutting + Printing + Stitching) must be "absorbed" by the remaining good balls in that order.
•	The Proposal: Use "Scrap Entry" within the Manufacturing Order. If  started with 100 balls and scrapped 5, the System should redistribute the total cost of 100 balls across the 95 good ones.







Material Issuance/consumption
To ensure the System provides an accurate cost for every ball at Reema Group, we have to distinguish between materials we can count (Components) and materials we "estimate" (Consumables).
Component Issuance: The "Strict Allocation" Model
Unlike the consumables (Latex/Oil) where we allow some "rough calculation," these components must follow a Strict Allocation rule in the System.
The Workflow:
1.	BoM Requirement: If the order is for 1,000 balls, the System calculates exactly:
o	250 Meters of PU (assuming 4 balls/meter).
o	1,000 Bladders.
o	1,000 Foam Sets (for HYB).
2.	The Requisition: Waleed doesn't just "rough guess" these; he approves a Picking List generated by the System.
3.	Physical Issue: The Storekeeper issues exactly 1,000 bladders. If 5 bladders are punctured during assembly, Ali Shan cannot just grab 5 more from the shelf. He must record a "Damaged Material Note" in the System to request replacements. This ensures  know exactly why r "Expected Cost" changed.
Consumable Material Issuance Strategy
Category 1: Product Costing (Option B - BoM Estimation)
•	Applied to: Latex (Lamination), Printing Inks, adhesive Chemicals.
•	System Logic: Every ball produced will automatically "consume" a set amount of these materials in the ERP (e.g., 15g of Latex).
•	Purpose: This ensures Irfan (Accountant) sees the correct cost for the order without needing Ali Shan to weigh every drop of glue.
Category 2: Physical Control (Option A - Direct Approval)
•	Applied to: Machine Oil, needles, clippers, blades etc.
•	System Logic: These are issued as "Floor Stock."
•	The "Waleed Gate": Before the Storekeeper releases a drum of oil or latex, Waleed must provide a digital approval in the System. His "rough calculation" (e.g., "This order of 5,000 balls needs exactly 2 kg/liters of ink") acts as the maximum limit.


The Workflow: Waleed (Production Manager)’s, Ali Shan, Floor supervisor Approval Chain
1.	Demand: The System shows an order for 5,000 Machine Stitched balls made by ali shan upon request of contractor.
2.	Calculation: Waleed reviews the order. He knows from experience that 5,000 balls need a certain amount of oil for the machines and latex for lamination and Approves or Modify it.
3.	The Storekeeper: Only sees the request after Waleed approves it. He issues the physical drum to the hall.
4.	Reconciliation: At the end of the order, if the ERP (Option B) says they should have used 1.8 drums, but Waleed approved 2.0 drums, the System flags the 0.2 drum difference as "Floor Waste."
________________________________________











1. The Sampling Workflow (Development Phase)
Before a production MO is even created, the System must track the "Base Model" creation:
Step	Action	Responsibility	System Output
1. Tech Pack	Customer sends a design or Reema Group creates a new ball spec.	Sales	Draft BoM
2. Lat Prep	Graphics team creates the Printing Lat (Vector) and Die-Cutting Lat.	Graphics Dept	Attachment to Product
3. Sample MO	A "Mini-MO" (usually for 2–5 balls) is created in the System.	Sampling Team	Sample MO
4. Physical Sample	The sample moves through the 17 halls (or a dedicated sample room).	Contractors	Labor Cost
5. Approval	Customer reviews the sample.	Client	Approved Base Model
________________________________________
2. The "Base Model" as a Master Template
Once the sample is approved, it becomes a Base Model in the ERP. When a real order arrives for 5,000 balls, the System must "inherit" three things from this Base Model:
A. The Bill of Materials (BoM)
•	It locks in the specific PU grade, bladder type, and thread color used in the sample.
B. The Printing Lat (The "Master File")
•	Requirement: The System must store the Printing Lat PDF/AI file directly on the product card.
•	Operational Logic: When Amir/Shamas (Printing) receive the panels, they open the System on their tablet, click the MO, and see the exact lat to ensure the logo placement matches the approved sample.
C. The Die-Cutting Pattern
•	The System must specify which "Die Number" (e.g., Die-32-Panel-Size-5) Afzal should use in the Cutting Hall.
________________________________________
3. Converting the Base Model into a Production MO
The logic for Waleed when he prepares the actual production:
1.	Selection: Waleed selects the Base Model (e.g., "Pro-Match-2026-V1").
2.	Order Entry: He enters the quantity (5,000).
3.	Auto-Generation: The System automatically generates the Material Requirements (how much PU, bladders, etc.) and the Work Orders for all 17 halls.
4.	Lat Link: The Printing Hall gets an automated alert with the approved artwork attached.
________________________________________
•	Version Control: We change the Printing Lat for a client (e.g., they update their logo), the System ensure the old lat is "Archived" so the Printing Hall doesn't accidentally use the wrong version
•	Lat Integration: System display the PDF/Image of the lat directly on the Production Screen for the printer and cutter to see
•	Prototype Costing: Track the cost of "Samples" separately from "Mass Production" so our R&D expenses don't get mixed with our Order Profits
•	Die-Cut Management: the System track the "Die Location"________________________________________





The SFG (Semi-Finished Goods) States
At each major hall, the material changes its "Identity." For (Accounts), this is vital because the value of the item increases every time a contractor touches it.
Stage	SFG Physical State	Transition Point	Process Logic & Ball Type
SFG-1	Laminated Sheets	Hall 2 (Lamination)	ALL: PU + Fabric joined.
SFG-2	Cut Panels	Hall 3 (Cutting)	ALL: Used for Yield Analysis.
SFG-3	Printed Panel Sets	Hall 4 (Printing)	ALL: Branded and ready for assembly.
SFG-4A	HS Stitched Shell	Hall 5 (ILO Gate)	HS ONLY: Returns from contractor Fully Stitched with bladder inside. Note: Skip Turning/Closing.
SFG-4B	Inverted Shell	Hall 6 (Stitching)	MS / HYB: Inside-out shell. No bladder yet.
SFG-4C	Reinforced Carcass	Hall 11 (Binding)	MS / HYB: The bladder is bound; ready for the heat mold.
SFG-5	Turned Shell	Hall 8 (Turning)	MS / HYB: Right-side out.
SFG-6	Molded Ball	Hall 12 (Molding)	THB ONLY: Panels fused to Carcass. Physically complete ball.
SFG-7	Filled & Closed Ball	Hall 10 (Closing)	MS / HYB: Bladder inserted and final seam hand-stitched.
 

2. Transformation Logic (How SFG becomes FG)
The System manages this through Work Orders. Each hall "consumes" one version of an SFG and results in next SFG.
•	The Component Trigger: When Ali Shan records a move from Stitching to Turning, the System automatically deducts the "Panel Sets" and "Bladders" from inventory and adds "Stitched Shells" to the WIP count.
•	Value Addition: The System adds the Contractor's Piece-Rate (e.g., Ali Mohsin’s stitching fee) to the value of that SFG.
________________________________________
3. The Final Transition to Finished Goods (FG)
A ball is only moved to the FG Warehouse after it passes through Hall 16 (Final QC) and Hall 17 (Packing).
•	The QC Barrier: The System should prevent any SFG from being marked as FG if it hasn't received a "Pass" digital stamp in the QC Hall.
•	The Packaging Link: In the Packing Hall, the System performs a final conversion: Individual Balls -> Export Cartons.
•	The Result: Sameer Mehmood (Sales) sees "Available to Ship" inventory only when the balls are in the FG Store.
________________________________________













The Costing Model
The System will calculate the value of a ball as a "Rolling Total" that grows at every hall. We will use the Actual Costing Method combined with Landed Cost and Overhead Absorption.
1. Raw Material Valuation (The Base)
We will not use "Estimated" or "Standard" prices for materials. The System must use the Actual Landed Cost.
•	Landed Cost Logic: The price of PU or Bladders must include:
o	Vendor Invoice Price
o	Inward Freight/Transport
o	Import Duties/Taxes (where applicable)
•	Inventory Method: We will use FIFO (First-In, First-Out). The System will consume the oldest batch of PU first, applying its specific landed cost to the SFG-1 (Laminated Sheets).
2. Value Addition (The Piece-Rate Injection)
As the product moves through the 17 Halls, the System "extracts" the labor cost and adds it to the Semi-Finished Good (SFG) value.
•	The Trigger: When Ali Shan performs a "Transfer" in the ERP (e.g., moving 500 balls from Stitching to Turning), the System automatically:
1.	Calculates the total labor ($Units \times Piece-Rate$).
2.	Debits the WIP (Work-in-Progress) Account.
3.	Credits the Contractor’s Payable Account (e.g., Ali Mohsin).
•	Result: The ball’s financial value increases in real-time as it moves across the floor.
3. Consumable Allocation (The Estimated Cost)
For items like Latex, Ink, and Thread, we use the Option B (BoM Estimation) approach.
•	Logic: The System adds a pre-calculated cost per ball for chemicals based on the Base Model/Sample specifications.
•	Reconciliation: Monthly, the Accountant (Irfan) will compare the "Total Estimated Consumption" vs. "Actual Stock Purchased" to adjust for any major variances.
4. Factory Overhead Absorption (The "True Profit" Layer)
To account for non-labor costs (Electricity, salary, Machine maintenance), we will apply an Overhead Absorption Rate.
•	Mechanism: A fixed "Factory Fee" per ball is added at the Final QC stage.
•	Benefit: This allows Management to see the Total Cost of Goods Sold (COGS), ensuring that even "Hidden Costs" are recovered in the client’s final invoice.

Summary of Cost Accumulation
Stage	Cost Components Added	Financial Status
Raw Store	Landed Material Cost	Raw Inventory Asset
Hall 3-12	Raw Material + Cumulative Piece Rates + Consumables	WIP (Semi-Finished Asset)
Hall 13-16	WIP + QC Labor + Factory Overheads	Finished Goods Asset
Hall 17	Finished Goods + Packing Material + Shipping	Cost of Goods Sold (COGS)




________________________________________________________________________________
ERP SYSTEM ARCHITECTURE & IMPLEMENTATION DECISIONS
________________________________________________________________________________
(Decided through discussion — May 2026)


1. MODULE STRUCTURE
────────────────────────────────────────────────────────────────────────────────
reema_sampling   — Sampling blueprints. Manages samples from creation through
                   client approval. Depends on mrp.
reema_invoice    — Pro Forma Invoices. Export staff workflow. Depends on
                   reema_sampling and account.
reema_mrp        — Manufacturing Orders, Work Orders, Piece Rate Matrix.
                   Extends Odoo's standard mrp module. Already installed.
                   Authored by Gemini CLI — has known bugs to fix.
mrp (Odoo)       — Standard Manufacturing module. Already installed and active.


2. AGREED PRODUCTION FLOW
────────────────────────────────────────────────────────────────────────────────

Sampling team creates blueprint
        ↓
Client approves physical sample
        ↓
Sampling team marks blueprint → "Sample Approved"
        ↓
  ┌─────────────────────────────┐    ┌──────────────────────────────────────┐
  │ Sameer creates invoice from │    │ Waleed gets notified → opens         │
  │ "Sample Approved" blueprint │    │ blueprint BOM button → defines       │
  │ and sends to client.        │    │ quantities at bulk scale, wastage    │
  │ No delay waiting for BOM.   │    │ factors, hall routing → marks        │
  └─────────────────────────────┘    │ blueprint "Production Ready"         │
                                     └──────────────────────────────────────┘
        ↓
Client accepts invoice
        ↓
Sameer clicks "Create Production Order" on accepted invoice
        ↓
System auto-creates:
  — One Production Order record (custom, linked to invoice)
  — One MO per invoice line (product + qty + BOM pre-filled from blueprint)
  — If BOM not ready: MO created with "BOM Pending" flag on Waleed's dashboard
        ↓
Waleed reviews Production Order on dashboard, adjusts quantities (e.g. +10%
QC buffer), confirms → Ali Shan sees Work Orders on his screen
        ↓
Ali Shan completes Work Orders hall by hall → SFG stock moves automatically
        ↓
Irfan reviews contractor payable entries → approves → payment processed


3. RESPONSIBILITY MODEL
────────────────────────────────────────────────────────────────────────────────
Person          Role                    System Access
──────────────────────────────────────────────────────────────────────────────
Sampling Team   Create blueprints,      Full access to reema_sampling.
                define materials at     Mark "Sample Approved".
                sample scale, mark
                Sample Approved.

Waleed          Complete BOM (bulk      Read-only on sampling blueprints.
(Production     quantities, wastage,    Smart button on blueprint → opens BOM.
Manager)        routing), mark          Full access to MOs and Work Centers.
                Production Ready,       Sees Production Order dashboard.
                manage MOs.

Sameer          Create invoices from    Full access to reema_invoice.
(Sales/Export)  approved blueprints,    No BOM access whatsoever.
                click Create
                Production Order.

Ali Shan        Complete Work Orders    Work order completion only.
(Production     hall by hall on the     Sees his queue per hall.
Assistant)      floor.

Irfan           Approve contractor      Accounting module — vendor bills,
(Accountant)    payable entries.        payables, costing reports.

Gatekeeper      Issue/receive HS        Gate security — stock moves for
                material to/from ILO    ILO issue and receive (Phase 2).
                contractors.


4. BOM ARCHITECTURE
────────────────────────────────────────────────────────────────────────────────
DECISION: Single MO per ball type + sfg_product_id per Work Center.

The BOM is a TEMPLATE — defined once per ball design, reused on every MO.
The BOM lives in Odoo standard mrp.bom, linked to the product (product_tmpl_id).
The sampling blueprint has product_tmpl_id → BOM is naturally linked via product.
A smart button on the blueprint opens the BOM directly for Waleed to complete.

Sampling team fills (at sample scale):
  — Material list (which products go into the ball)

Waleed fills (at bulk production scale):
  — Exact quantities per ball with wastage buffer
  — Which component is consumed at which specific work order step
    (e.g. Bladder consumed at Hall 9, Foam consumed at Hall 7)
  — Hall routing (operations sequence based on construction type)
  — Contractor per operation
  — Piece rate auto-looked up from reema.piece.rate matrix

Construction type determines routing:
  MS:  Hall 2→3→4→6→8→9→10→13→14→15→16→17
  HYB: Hall 2→3→4→6→7→8→9→10→13→14→15→16→17
  THB: Hall 2→3→4→11→12→13→14→15→16→17
  HS:  Hall 2→3→4→[ILO external]→13→14→15→16→17 (Phase 2)


5. SFG TRACKING ARCHITECTURE — sfg_product_id per Work Center
────────────────────────────────────────────────────────────────────────────────
DECISION: All 4 SFG criteria (count in WIP, detect waste, track location,
management visibility) apply at every major hall. Solution: use the
sfg_product_id field already defined on MrpWorkcenter in reema_mrp.

ONE MO per ball type. ONE set of Work Orders flowing through all halls.
When Ali Shan completes a work order (button_finish), the system:
  1. Deducts the input SFG from WIP stock (previous hall's output)
  2. Adds this hall's sfg_product_id to WIP stock (quantity = qty_produced)
  3. The difference = waste/scrap at that stage

Work Center to SFG Product mapping:
  Hall 2  (Lamination)      → Laminated Sheet
  Hall 3  (Cutting)         → Cut Panel Set
  Hall 4  (Printing)        → Printed Panel Set
  Hall 6  (Stitching MS/HYB)→ Stitched Shell
  Hall 7  (Foam Attach HYB) → Foam-Applied Shell
  Hall 8  (Turning)         → Turned Shell
  Hall 9  (Bladder)         → Shell with Bladder
  Hall 10 (Closing)         → Closed Ball
  Hall 11 (THB Binding)     → Bound Carcass
  Hall 12 (THB Molding)     → Molded Ball
  Hall 14 (Shaping)         → Shaped Ball
  Hall 15 (Cleaning)        → Cleaned Ball
  Hall 15b(Seam Sealing)    → Sealed Ball
  Hall 17 (Packing)         → Packed Carton (Finished Good)

This gives full WIP counting and waste detection at every stage with only
ONE MO per ball type (not 13 cascading MOs).

The button_finish override in reema_mrp/models/mrp_workorder.py has the
hook but no implementation — this stock movement logic must be written.

SFG products are extensible: add or remove SFG products at any stage at
any time by updating the Work Center's sfg_product_id field. Existing
in-progress MOs are not affected.


6. BLUEPRINT STATUSES — NEW STATUSES TO ADD
────────────────────────────────────────────────────────────────────────────────
Current:  draft → in_progress → completed → shipped → cancelled
New:      draft → in_progress → sample_approved → production_ready
                                    → completed → shipped

sample_approved:  Sampling team marks this when client physically approves
                  the sample. Triggers notification to Waleed. Sameer can
                  now add this blueprint to an invoice.

production_ready: Waleed marks this after completing the BOM (quantities,
                  routing, wastage). Blueprint is fully ready for bulk
                  production MO creation.


7. PIECE RATE MATRIX
────────────────────────────────────────────────────────────────────────────────
Model already built in reema_mrp (reema.piece.rate).
Links: hall (mrp.workcenter) + construction_type + ball_size + complexity → rate.
Status: DEFERRED to Phase 2.
Reason: Cannot be properly filled until the 17 Work Centers are set up in Odoo.
        Once work centers exist and Phase 1 is stable, Waleed reviews and
        populates the matrix. Piece-rate auto-calculation on work order
        completion then activates automatically.


8. HS BALL / ILO CONTRACTOR TRACKING
────────────────────────────────────────────────────────────────────────────────
Status: DEFERRED to Phase 3.
Reason: Requires subcontracting flow (Printed Panel Sets issued to external
        ILO contractors, Stitched Shells received back). Complex enough to
        be its own phase. MS, HYB, THB are prioritised first.


9. EXISTING reema_mrp STATUS & KNOWN BUGS
────────────────────────────────────────────────────────────────────────────────
Module is installed and active. Contains:
  — reema.piece.rate model (Piece Rate Matrix)
  — mrp.production extension: construction_type, ball_size, complexity_level
  — mrp.workorder extension: contractor_id, piece_rate_id, labor_cost
  — mrp.workcenter extension: is_qc_point, sfg_product_id
  — button_finish hook (stock movement logic NOT yet implemented)

Known bugs to fix before Phase 1:
  1. Duplicate line in mrp_workorder.py line 14 — piece rate search broken
  2. wizard/ directory is empty but imported in __init__.py — import error risk
  3. ir_sequence_data.xml not listed in manifest — sequence never loaded
  4. Security too open — base.group_user has full CRUD on piece rates
     (should be restricted to Waleed / admin only)


10. IMPLEMENTATION PHASES
────────────────────────────────────────────────────────────────────────────────
PHASE 1 — Foundation (build first):
  Goal: Invoice accepted → MOs appear on Waleed's dashboard with BOM pre-filled.
        Waleed confirms → Ali Shan sees Work Orders per hall.

  Tasks:
  — Fix reema_mrp bugs (duplicate line, wizard import, sequence, security)
  — Add sample_approved and production_ready statuses to blueprint
  — Add smart button on blueprint → opens BOM for that product (Waleed's entry point)
  — Notify Waleed (Odoo activity) when blueprint is marked Sample Approved
  — Set up 17 Work Centers in Odoo (data setup — one per hall)
  — Set up SFG products for all stages (data setup)
  — Assign sfg_product_id on each Work Center
  — Implement button_finish stock movement logic in reema_mrp
  — "Create Production Order" button on accepted invoice
  — Production Order model (groups all MOs under one invoice, Waleed's dashboard)
  — Access control: Waleed group (read-only blueprints, full MOs)
  — Restrict invoice lines to Sample Approved or Production Ready blueprints

PHASE 2 — Production Floor & Costing:
  Goal: Live WIP tracking, material consumption, piece-rate payables.

  Tasks:
  — Ali Shan work order interface (mobile-friendly, simple per-hall view)
  — Material consumption at correct work order step (Consumed in Operation)
  — SFG stock movements at each hall completion (Phase 1 lays groundwork)
  — Piece rate matrix filled in (after work centers are set up in Phase 1)
  — Contractor payable auto-entry when work order confirmed
  — Irfan payable approval flow
  — QC pass / rework / reject buttons (Hall 13 and Hall 16)

PHASE 3 — Quality, HS & Advanced Costing:
  Goal: Full production control, HS ball tracking, accurate COGS.

  Tasks:
  — HS ball ILO tracking (subcontracting — issue panel sets, receive shells)
  — QC rejection cost redistribution across remaining good balls
  — Yield gap variance reporting (input vs output per hall)
  — Wastage factor analysis per order
  — Full COGS calculation per order
  — Overhead absorption at Final QC stage

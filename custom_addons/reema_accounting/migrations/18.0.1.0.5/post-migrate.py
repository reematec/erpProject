def migrate(cr, version):
    """Repair Labor Expense Account moves off the company-wide
    reema_repair_expense_account_id setting onto the Initial QC / Final QC
    work centers' own expense_account_id (same as every other hall), and is
    corrected from 5-2-1-16 (Labor — Repair) to 5-2-1-15 (Labor — Hand
    Stitching) — ILO is the hand-stitching contractor network.
    """
    cr.execute("""
        UPDATE mrp_workcenter wc
        SET expense_account_id = aa.id
        FROM account_account aa
        WHERE (wc.is_initial_qc OR wc.is_final_qc)
          AND aa.code_store->>'1' = '5-2-1-15'
    """)

def migrate(cr, version):
    """Initial QC pass-qty entries are the real ILO payable line — their rate was
    never being set, and they were wrongly marked payment_excluded (that flag is
    for the provisional Issuance/Receive entries only). Backfill the rate from
    each entry's matching Stitching Center Issuance line and re-include them in
    payment so they show up as Unbilled.
    """
    cr.execute("""
        UPDATE reema_wo_batch_entry be
        SET piece_rate_id = issuance_be.piece_rate_id,
            payment_excluded = FALSE,
            exclusion_reason = NULL
        FROM mrp_workorder wo
        JOIN mrp_workcenter wc ON wc.id = wo.workcenter_id
        JOIN mrp_production mo ON mo.id = wo.production_id
        JOIN reema_ilo_dispatch disp ON disp.mo_id = mo.id AND disp.dispatch_type = 'stitching'
        JOIN reema_wo_batch_entry issuance_be ON issuance_be.id = disp.batch_entry_id
        WHERE be.workorder_id = wo.id
          AND wc.is_initial_qc = TRUE
          AND be.is_billed = FALSE
          AND disp.contractor_id = be.contractor_id
    """)

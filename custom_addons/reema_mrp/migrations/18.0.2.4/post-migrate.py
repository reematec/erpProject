def migrate(cr, version):
    """Backfill dispatch_type/original_contractor_id on existing ILO dispatch
    rows created before the Initial QC + repair loop feature existed — they
    were all plain stitching dispatches, so original_contractor_id is just
    their own contractor_id.
    """
    cr.execute("""
        UPDATE reema_ilo_dispatch
        SET dispatch_type = 'stitching', original_contractor_id = contractor_id
        WHERE original_contractor_id IS NULL
    """)

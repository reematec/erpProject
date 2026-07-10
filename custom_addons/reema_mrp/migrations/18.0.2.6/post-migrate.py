def migrate(cr, version):
    """Final QC now has its own repair loop, distinct from Initial QC's. Backfill
    repair_source on existing repair-type dispatches — all of them came from
    Initial QC, since Final QC's repair mechanism didn't exist before this.
    """
    cr.execute("""
        UPDATE reema_ilo_dispatch
        SET repair_source = 'initial_qc'
        WHERE dispatch_type = 'repair' AND repair_source IS NULL
    """)

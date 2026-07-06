def migrate(cr, version):
    """Backfill stock_move.reema_batch_entry_id for backflush moves created
    before that FK existed.

    Those moves were only linked to their batch entry via a formatted
    'origin' string (mo.name / wo.name / batch.name). A sequence prefix
    change (4-digit -> 2-digit year) later renamed every mrp.production and
    reema.wo.batch.entry record, so the stored origin strings went stale and
    stopped matching current names — making the "Consumed" column read 0
    everywhere. Reconstruct the match by normalizing any embedded 4-digit
    year (/20XX/) down to 2-digit (/XX/) before comparing; this is a no-op
    for origins that already use the short format.
    """
    cr.execute("""
        UPDATE stock_move sm
        SET reema_batch_entry_id = be.id
        FROM reema_wo_batch_entry be
        JOIN mrp_workorder wo ON wo.id = be.workorder_id
        JOIN mrp_production mo ON mo.id = wo.production_id
        WHERE sm.name LIKE 'Backflush:%'
          AND sm.reema_batch_entry_id IS NULL
          AND regexp_replace(sm.origin, '/20(\\d\\d)/', '/\\1/', 'g')
              = mo.name || ' / ' || wo.name || ' / ' || be.name
    """)

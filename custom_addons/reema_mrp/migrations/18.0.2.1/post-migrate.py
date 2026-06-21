def migrate(cr, version):
    """Carry per-operation Impressions/Ball onto the owning BOM, then drop the
    now-removed per-operation column.

    Runs after the new mrp_bom.impressions_per_ball column is created and while
    the old mrp_routing_workcenter column still exists (Odoo leaves removed-field
    columns in place), so both are available for the copy.
    """
    cr.execute("""
        UPDATE mrp_bom b
        SET impressions_per_ball = rwc.impressions_per_ball
        FROM mrp_routing_workcenter rwc
        WHERE rwc.bom_id = b.id
          AND rwc.impressions_per_ball IS NOT NULL
          AND rwc.impressions_per_ball > 0
    """)
    cr.execute("ALTER TABLE mrp_routing_workcenter DROP COLUMN IF EXISTS impressions_per_ball")

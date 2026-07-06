import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """ILO payment now flows through the Stitching Center Receive step instead
    of the Issuance-time batch entry. Exclude any existing unbilled Issuance
    entries from payment so they can't be double-billed alongside the new
    receive-driven entries. Already-billed ones are left untouched — that's a
    real vendor bill, not something a migration should silently touch.
    """
    cr.execute("""
        UPDATE reema_wo_batch_entry be
        SET payment_excluded = TRUE,
            exclusion_reason = 'ILO — paid via Stitching Center Receive (auto-excluded by migration 18.0.2.3)'
        FROM mrp_workorder wo JOIN mrp_workcenter wc ON wc.id = wo.workcenter_id
        WHERE be.workorder_id = wo.id AND wc.is_ilo = TRUE
          AND be.is_billed = FALSE AND be.payment_excluded = FALSE
    """)
    cr.execute("""
        SELECT COUNT(*) FROM reema_wo_batch_entry be
        JOIN mrp_workorder wo ON wo.id = be.workorder_id
        JOIN mrp_workcenter wc ON wc.id = wo.workcenter_id
        WHERE wc.is_ilo = TRUE AND be.is_billed = TRUE
    """)
    count = cr.fetchone()[0]
    if count:
        _logger.warning(
            '%s already-billed ILO Issuance-side batch entries exist — '
            'left untouched, review manually for possible overpayment.', count
        )

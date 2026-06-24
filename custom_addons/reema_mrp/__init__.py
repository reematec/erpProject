from . import models
from . import wizard


def post_init_hook(env):
    """Copy pay_basis from existing BOM operations to their work centers.
    The mrp_routing_workcenter.pay_basis column still exists in the DB
    after removal from the model — Odoo never drops columns on upgrade."""
    env.cr.execute("""
        UPDATE mrp_workcenter wc
        SET pay_basis = subq.pay_basis
        FROM (
            SELECT DISTINCT ON (workcenter_id)
                   workcenter_id, pay_basis
            FROM   mrp_routing_workcenter
            WHERE  pay_basis IS NOT NULL
            ORDER  BY workcenter_id, id
        ) subq
        WHERE wc.id = subq.workcenter_id
    """)

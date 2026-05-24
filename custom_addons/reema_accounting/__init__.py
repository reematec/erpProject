from . import models


def post_init_hook(env):
    # Cancel the pending generic_coa auto-install so it doesn't wipe our COA
    if hasattr(env.registry, '_auto_install_template'):
        del env.registry._auto_install_template
    # Mark the company so future upgrades don't re-trigger auto-install
    company = env.company
    if not company.chart_template:
        company.write({'chart_template': 'generic_coa'})

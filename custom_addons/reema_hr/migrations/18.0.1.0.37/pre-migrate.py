def migrate(cr, version):
    """Backfill the new required period_month/period_year columns from each
    existing payslip's own date_from, before Odoo's _auto_init adds the NOT
    NULL constraint (which would otherwise use today's date as the default
    for every existing row, corrupting historical periods)."""
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'reema_hr_payslip' AND column_name = 'period_month'
    """)
    if cr.fetchone():
        return

    cr.execute("ALTER TABLE reema_hr_payslip ADD COLUMN period_month VARCHAR")
    cr.execute("ALTER TABLE reema_hr_payslip ADD COLUMN period_year INTEGER")
    cr.execute("""
        UPDATE reema_hr_payslip
        SET period_month = EXTRACT(MONTH FROM date_from)::text,
            period_year = EXTRACT(YEAR FROM date_from)::integer
        WHERE date_from IS NOT NULL
    """)

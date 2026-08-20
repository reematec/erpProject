def migrate(cr, version):
    # ir_sequence_data.xml is noupdate="1" — editing its <field name="prefix">
    # in XML has no effect on the already-installed DB record, so update it
    # directly here instead. Prefix passed as a query PARAM, not inlined into
    # the SQL string — it contains literal "%(y)s"/"%(month)s", which
    # psycopg2 would otherwise try to interpret as its own placeholder syntax.
    cr.execute(
        "UPDATE ir_sequence SET prefix = %s WHERE code = %s",
        ('PAY/%(y)s/%(month)s/', 'reema.hr.payslip'),
    )

{
    'name': 'Reema HR',
    'version': '18.0.1.0.12',
    'category': 'Human Resources',
    'summary': 'Attendance, Salary Advances, Employee Loans and Payroll for Reema Tec',
    'description': """
        HR module covering employee lifecycle (hiring/firing/quitting via core HR),
        daily attendance with late-arrival deduction, salary advances, employee
        loans with installment recovery, and monthly payslips posted to Accounting.
    """,
    'author': 'Reema Tec',
    'depends': ['hr', 'reema_accounting'],
    'data': [
        'security/reema_hr_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/res_company_views.xml',
        'views/hr_employee_views.xml',
        'views/reema_hr_attendance_views.xml',
        'views/reema_hr_public_holiday_views.xml',
        'views/reema_hr_employee_advance_views.xml',
        'views/reema_hr_payslip_views.xml',
        'views/reema_hr_menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}

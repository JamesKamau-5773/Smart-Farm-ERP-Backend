"""What a payslip shows, built from a payroll run's stored line. Never recalculated."""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from decimal import Decimal

from app.models.hr import EMPLOYEE_STATUTORY_FIELDS, PayrollRun, PayrollRunLineItem


def _money(value) -> str:
    return f'{Decimal(str(value or 0)):,.2f}'


def _lines(*pairs) -> list[dict]:
    return [{'label': label, 'amount': _money(amount)} for label, amount in pairs if Decimal(str(amount or 0)) > 0]


class PayslipView:
    @staticmethod
    def build(run: PayrollRun, item: PayrollRunLineItem, *, employer_name: str, role=None, id_number=None) -> dict:
        def amount(field):
            return Decimal(str(getattr(item, field) or 0))

        earned = amount('gross_pay') - amount('leave_deduction') - amount('overdue_penalty_deduction')
        total_deductions = sum((amount(field) for field in EMPLOYEE_STATUTORY_FIELDS), Decimal('0')) + amount('advance_deduction')
        loan_after = max(amount('loan_balance') - amount('advance_deduction'), Decimal('0'))
        return {
            'employer_name': employer_name,
            'period_label': f'{calendar.month_name[run.payroll_month]} {run.payroll_year}',
            'run_status': run.status,
            'staff_name': item.staff_name,
            'role': role,
            'id_number': id_number,
            'days_paid': item.days_paid,
            'gross_pay': _money(item.gross_pay),
            'earnings_deductions': _lines(
                (f'Unpaid leave ({item.approved_leave_days} days)', item.leave_deduction),
                (f'Unpaid absence ({item.overdue_penalty_days} days)', item.overdue_penalty_deduction),
            ),
            'earned_pay': _money(earned),
            'deductions': _lines(
                ('PAYE', item.paye),
                ('NSSF', item.nssf_employee),
                ('SHIF', item.shif),
                ('Housing Levy', item.housing_levy_employee),
                ('Advance recovery', item.advance_deduction),
            ),
            'total_deductions': _money(total_deductions),
            'net_pay': _money(item.net_pay),
            'employer_contributions': _lines(('NSSF (employer)', item.nssf_employer), ('Housing Levy (employer)', item.housing_levy_employer)),
            'taxable_pay': _money(item.taxable_pay) if item.statutory_rates_version else None,
            'rates_version': item.statutory_rates_version,
            'loan_balance_after': _money(loan_after),
            'generated_at': datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC'),
        }

"""One employee's pay for one payroll month. Pure calculation.

Order: contractual pay for the days employed -> unpaid leave and absence ->
statutory deductions on what was earned -> advance recovery from whatever is
left. An advance is never recovered at the cost of statutory deductions, and
net pay never goes below zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app.services.kenya_statutory_deductions import KenyaStatutoryDeductions, StatutoryBreakdown

CENT = Decimal('0.01')


@dataclass(frozen=True)
class PayLineInput:
    base_salary: Decimal
    period_start: date
    month_days: int
    leave_days: int
    absence_days: int
    loan_balance: Decimal
    monthly_deduction: Decimal
    statutory_enabled: bool
    # Days employed in the month when the employee left during it; None for the full month.
    days_paid: Optional[int] = None


@dataclass(frozen=True)
class PayLine:
    gross_pay: Decimal
    leave_deduction: Decimal
    absence_deduction: Decimal
    earned_pay: Decimal
    statutory: StatutoryBreakdown
    advance_deduction: Decimal
    net_pay: Decimal

    @property
    def total_deductions(self) -> Decimal:
        return self.leave_deduction + self.absence_deduction + self.statutory.employee_total + self.advance_deduction


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class PayrollLineCalculator:
    @staticmethod
    def calculate(line: PayLineInput) -> PayLine:
        base = Decimal(line.base_salary)
        daily_rate = base / Decimal(line.month_days)
        gross = _money(base if line.days_paid is None else daily_rate * Decimal(line.days_paid))

        leave_deduction = min(_money(daily_rate * Decimal(line.leave_days)), gross)
        absence_deduction = min(_money(daily_rate * Decimal(line.absence_days)), gross - leave_deduction)
        earned = gross - leave_deduction - absence_deduction

        statutory = (
            KenyaStatutoryDeductions.calculate(earned, line.period_start)
            if line.statutory_enabled else KenyaStatutoryDeductions.none(earned)
        )
        after_statutory = max(earned - statutory.employee_total, Decimal('0.00'))

        loan_balance = max(Decimal(line.loan_balance), Decimal('0'))
        advance = _money(min(Decimal(line.monthly_deduction), loan_balance, after_statutory)) if loan_balance > 0 else Decimal('0.00')

        return PayLine(
            gross_pay=gross,
            leave_deduction=leave_deduction,
            absence_deduction=absence_deduction,
            earned_pay=earned,
            statutory=statutory,
            advance_deduction=max(advance, Decimal('0.00')),
            net_pay=_money(after_statutory - max(advance, Decimal('0.00'))),
        )

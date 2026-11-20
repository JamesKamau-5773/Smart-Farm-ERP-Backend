"""Who is paid for a payroll month, and their line items. No persistence.

Leave, absence and days-employed are worked out here from the employee
record; the money is calculated by ``PayrollLineCalculator``.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from app.models.hr import EMPLOYEE_STATUTORY_FIELDS, STATUTORY_FIELDS, PayrollRunLineItem
from app.services.employee_status_policy import EmployeeStatusPolicy
from app.services.payroll_line_calculator import PayLineInput, PayrollLineCalculator


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


@dataclass(frozen=True)
class RunTotals:
    gross: Decimal
    net: Decimal
    deductions: Decimal


class PayrollRunBuilder:
    def __init__(self, payroll_year: int, payroll_month: int):
        self.year = payroll_year
        self.month = payroll_month
        self.period_start = date(payroll_year, payroll_month, 1)
        self.month_days = calendar.monthrange(payroll_year, payroll_month)[1]
        self.period_end = date(payroll_year, payroll_month, self.month_days)

    def eligible(self, employees: Iterable) -> list:
        """Everyone still employed at some point in the month."""
        return [employee for employee in employees if employee.end_date is None or employee.end_date >= self.period_start]

    def build_line_items(self, employees: Iterable) -> list[PayrollRunLineItem]:
        return [self.build_line_item(employee) for employee in employees]

    def build_line_item(self, employee) -> PayrollRunLineItem:
        leave_days = self.leave_days(employee)
        absence_days = self.absence_days(employee)
        days_paid = self.days_paid(employee)
        pay = PayrollLineCalculator.calculate(PayLineInput(
            base_salary=_decimal(employee.base_salary),
            period_start=self.period_start,
            month_days=self.month_days,
            leave_days=leave_days,
            absence_days=absence_days,
            loan_balance=_decimal(employee.loan_balance),
            monthly_deduction=_decimal(employee.monthly_deduction),
            statutory_enabled=bool(employee.statutory_deductions_enabled),
            days_paid=days_paid,
        ))
        return PayrollRunLineItem(
            staff_id=employee.id,
            staff_name=employee.full_name,
            status=EmployeeStatusPolicy.current_status(employee),
            base_salary=_decimal(employee.base_salary),
            approved_leave_days=leave_days,
            overdue_penalty_days=absence_days,
            leave_deduction=pay.leave_deduction,
            overdue_penalty_deduction=pay.absence_deduction,
            advance_deduction=pay.advance_deduction,
            gross_pay=pay.gross_pay,
            net_pay=pay.net_pay,
            loan_balance=_decimal(employee.loan_balance),
            monthly_deduction=_decimal(employee.monthly_deduction),
            leave_type=employee.leave_type,
            leave_start_date=employee.leave_start_date,
            leave_end_date=employee.leave_end_date,
            expected_return_date=employee.expected_return_date,
            actual_return_date=employee.actual_return_date,
            days_paid=days_paid,
            statutory_rates_version=pay.statutory.rates_version,
            **{field: getattr(pay.statutory, field) for field in STATUTORY_FIELDS},
        )

    @staticmethod
    def totals(line_items: Iterable[PayrollRunLineItem]) -> RunTotals:
        line_items = list(line_items)

        def total(*fields):
            return sum((_decimal(getattr(item, field)) for item in line_items for field in fields), Decimal('0'))

        return RunTotals(
            gross=total('gross_pay'),
            net=total('net_pay'),
            deductions=total('leave_deduction', 'overdue_penalty_deduction', 'advance_deduction', *EMPLOYEE_STATUTORY_FIELDS),
        )

    def days_paid(self, employee) -> Optional[int]:
        """Days employed in the month for someone who left during it; None for a full month."""
        end_date = employee.end_date
        if end_date and end_date.year == self.year and end_date.month == self.month:
            return end_date.day
        return None

    def leave_days(self, employee) -> int:
        if employee.unpaid_leave_days_this_month:
            return int(employee.unpaid_leave_days_this_month)
        start_date = employee.leave_start_date
        end_date = employee.leave_end_date or employee.expected_return_date or employee.actual_return_date
        if not start_date or not end_date:
            return 0
        overlap_start = max(start_date, self.period_start)
        overlap_end = min(end_date, self.period_end)
        if overlap_end < overlap_start:
            return 0
        return (overlap_end - overlap_start).days + 1

    def absence_days(self, employee) -> int:
        """Days overdue from leave by the end of the month."""
        if not employee.expected_return_date or employee.actual_return_date:
            return 0
        if employee.expected_return_date >= self.period_end:
            return 0
        return max((self.period_end - employee.expected_return_date).days, 0)

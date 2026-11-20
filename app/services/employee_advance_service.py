"""Salary advances: the only way an employee's advance balance changes.

Every change locks the employee row, applies the amount on the server and
appends an ``EmployeeLoanMovement``, so two advances issued at the same time
both count and the balance always matches its history.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.models.hr import Employee, EmployeeLoanMovement, LoanMovementKind
from app.repositories.hr_repo import EmployeeLoanMovementRepository, EmployeeRepository
from app.services.advance_ledger_service import AdvanceLedgerService
from app.utils.api_errors import ApiError
from app.utils.farm_time import farm_today
from app.utils.unit_of_work import unit_of_work

CENT = Decimal('0.01')


def _amount(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ApiError('VALIDATION_ERROR', 'amount must be a number.')
    if not amount.is_finite() or amount <= 0:
        raise ApiError('VALIDATION_ERROR', 'amount must be greater than 0.')
    return amount


def _occurred_on(value) -> date:
    if value in (None, ''):
        return farm_today()
    try:
        occurred = date.fromisoformat(str(value))
    except ValueError:
        raise ApiError('VALIDATION_ERROR', 'date must be in YYYY-MM-DD format.')
    if occurred > farm_today():
        raise ApiError('VALIDATION_ERROR', 'date cannot be in the future.')
    return occurred


class EmployeeAdvanceService:
    @staticmethod
    def issue(tenant_id: int, employee_id: int, data: dict, *, actor_id: Optional[int], farm_id: Optional[int]) -> EmployeeLoanMovement:
        """Pays an advance. By default it is also posted to the ledger, since cash leaves the farm."""
        amount = _amount(data.get('amount'))
        occurred_on = _occurred_on(data.get('date') or data.get('issued_on'))
        record_expense = data.get('record_expense', True) is not False
        with unit_of_work():
            employee = EmployeeAdvanceService._lock(tenant_id, employee_id)
            if employee.end_date is not None:
                raise ApiError('EMPLOYEE_OFFBOARDED', 'Advances cannot be issued to an employee who has left.', 409)
            employee.loan_balance = Decimal(employee.loan_balance or 0) + amount
            ledger_entry = (
                AdvanceLedgerService.post_advance(employee, amount, occurred_on, actor_id=actor_id, farm_id=farm_id)
                if record_expense else None
            )
            return EmployeeAdvanceService._append(
                employee, LoanMovementKind.ADVANCE, amount, occurred_on=occurred_on,
                note=data.get('note'), ledger_entry=ledger_entry, actor_id=actor_id,
            )

    @staticmethod
    def repay(tenant_id: int, employee_id: int, data: dict, *, actor_id: Optional[int]) -> EmployeeLoanMovement:
        """Cash the employee paid back outside payroll."""
        amount = _amount(data.get('amount'))
        occurred_on = _occurred_on(data.get('date'))
        with unit_of_work():
            employee = EmployeeAdvanceService._lock(tenant_id, employee_id)
            balance = Decimal(employee.loan_balance or 0)
            if amount > balance:
                raise ApiError('VALIDATION_ERROR', f'Repayment is more than the outstanding balance of {balance:.2f}.')
            employee.loan_balance = balance - amount
            return EmployeeAdvanceService._append(
                employee, LoanMovementKind.REPAYMENT, amount, occurred_on=occurred_on,
                note=data.get('note'), actor_id=actor_id,
            )

    @staticmethod
    def stage_payroll_deduction(tenant_id: int, employee_id: int, amount: Decimal, *, payroll_run, actor_id=None) -> None:
        """Recovers an advance through a paid payroll run. The caller commits."""
        employee = EmployeeAdvanceService._lock(tenant_id, employee_id)
        balance = Decimal(employee.loan_balance or 0)
        recovered = min(amount, balance)
        if recovered <= 0:
            return
        employee.loan_balance = balance - recovered
        EmployeeAdvanceService._append(
            employee, LoanMovementKind.PAYROLL_DEDUCTION, recovered,
            occurred_on=farm_today(), payroll_run=payroll_run, actor_id=actor_id,
            note=f'Payroll {payroll_run.payroll_year:04d}-{payroll_run.payroll_month:02d}',
        )

    @staticmethod
    def stage_opening_balance(employee: Employee, *, actor_id=None) -> None:
        """Records the balance an employee joined with, so history starts from it. The caller commits."""
        balance = Decimal(employee.loan_balance or 0)
        if balance > 0:
            EmployeeAdvanceService._append(
                employee, LoanMovementKind.ADVANCE, balance, occurred_on=farm_today(),
                note='Opening balance', actor_id=actor_id,
            )

    @staticmethod
    def history(tenant_id: int, employee_id: int) -> tuple[Employee, list[EmployeeLoanMovement]]:
        employee = EmployeeRepository.get_by_id_for_tenant(employee_id, tenant_id)
        if employee is None:
            raise ApiError('NOT_FOUND', 'Employee not found for this tenant.', 404)
        return employee, EmployeeLoanMovementRepository.list_for_employee(tenant_id, employee_id)

    @staticmethod
    def has_history(employee: Employee) -> bool:
        return (
            Decimal(employee.loan_balance or 0) > 0
            or EmployeeLoanMovementRepository.exists_for_employee(employee.tenant_id, employee.id)
        )

    @staticmethod
    def _lock(tenant_id: int, employee_id: int) -> Employee:
        employee = EmployeeRepository.get_for_update(employee_id, tenant_id)
        if employee is None:
            raise ApiError('NOT_FOUND', 'Employee not found for this tenant.', 404)
        return employee

    @staticmethod
    def _append(employee: Employee, kind: str, amount: Decimal, *, occurred_on: date, note=None,
                payroll_run=None, ledger_entry=None, actor_id=None) -> EmployeeLoanMovement:
        return EmployeeLoanMovementRepository.stage(EmployeeLoanMovement(
            tenant_id=employee.tenant_id,
            employee_id=employee.id,
            kind=kind,
            amount=amount,
            balance_after=Decimal(employee.loan_balance or 0),
            occurred_on=occurred_on,
            note=(note or '').strip() or None,
            payroll_run_id=payroll_run.id if payroll_run is not None else None,
            ledger_transaction_id=ledger_entry.id if ledger_entry is not None else None,
            recorded_by=actor_id,
        ))

"""The payroll run lifecycle: draft -> finalized (expense posted) -> paid (advances recovered)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.models.hr import PayrollRun, PayrollRunStatus
from app.repositories.hr_repo import EmployeeRepository, PayrollRepository
from app.services.employee_advance_service import EmployeeAdvanceService
from app.services.employee_status_policy import EmployeeStatusPolicy
from app.services.hr_serializers import PayrollRunSerializer
from app.services.payroll_ledger_service import PayrollLedgerService
from app.services.payroll_run_builder import PayrollRunBuilder
from app.utils.api_errors import ApiError
from app.utils.unit_of_work import unit_of_work


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_period(run_id: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in str(run_id).split('-', 1))
    except (TypeError, ValueError):
        raise ApiError('VALIDATION_ERROR', 'run_id must be in YYYY-MM format.')
    return year, month


class PayrollRunService:
    @staticmethod
    def create(tenant_id: int, data: dict, *, generated_by=None, farm_id=None) -> dict:
        year, month = PayrollRunService._requested_period(data)
        builder = PayrollRunBuilder(year, month)
        employees = builder.eligible(EmployeeRepository.list_by_tenant(tenant_id))
        if not employees:
            raise ApiError('CONFLICT', 'Cannot generate payroll because no employees are registered.', 409)

        existing = PayrollRepository.get_run(tenant_id=tenant_id, payroll_year=year, payroll_month=month)
        if existing and (existing.status != PayrollRunStatus.DRAFT or existing.line_items):
            return PayrollRunService._existing(existing)

        try:
            with unit_of_work():
                if existing:
                    PayrollRepository.stage_delete_run(existing)
                EmployeeStatusPolicy.synchronize(employees)
                line_items = builder.build_line_items(employees)
                totals = builder.totals(line_items)
                run = PayrollRepository.stage_run(PayrollRun(
                    tenant_id=tenant_id,
                    farm_id=farm_id,
                    payroll_year=year,
                    payroll_month=month,
                    generated_by=_int_or_none(generated_by),
                    total_gross_pay=totals.gross,
                    total_net_pay=totals.net,
                    total_deductions=totals.deductions,
                    notes=data.get('notes'),
                ), line_items)
        except IntegrityError:
            # Another request generated the same period first.
            concurrent = PayrollRepository.get_run(tenant_id=tenant_id, payroll_year=year, payroll_month=month)
            if concurrent is None:
                raise
            return PayrollRunService._existing(concurrent)
        return {
            'message': 'Payroll draft generated successfully. Finalize it to post the labor expense.',
            'ledger_posted': False,
            **PayrollRunSerializer.serialize(run),
        }

    @staticmethod
    def list_runs(tenant_id: int) -> list[dict]:
        return [
            PayrollRunSerializer.serialize(run, include_lines=False)['run']
            for run in PayrollRepository.list_runs(tenant_id=tenant_id)
        ]

    @staticmethod
    def get(tenant_id: int, run_id: str) -> dict:
        return PayrollRunSerializer.serialize(PayrollRunService.find(tenant_id, run_id))

    @staticmethod
    def finalize(tenant_id: int, run_id: str, *, actor_id=None, farm_id=None) -> dict:
        with unit_of_work():
            run = PayrollRunService.find(tenant_id, run_id, for_update=True)
            if run.status in (PayrollRunStatus.FINALIZED, PayrollRunStatus.PAID):
                message = 'Payroll already finalized; labor expense reconciled.'
            elif run.status != PayrollRunStatus.DRAFT:
                raise ApiError('CONFLICT', f'Payroll run cannot be finalized from {run.status}.', 409)
            elif not run.line_items:
                raise ApiError('CONFLICT', 'Cannot finalize a payroll run with no employees.', 409)
            else:
                run.status = PayrollRunStatus.FINALIZED
                run.finalized_at = datetime.now(timezone.utc)
                run.finalized_by = _int_or_none(actor_id)
                message = 'Payroll finalized and labor expense posted.'
            ledger_transaction = PayrollRunService._post_ledger(run, actor_id=actor_id, farm_id=farm_id)
        return {
            'message': message,
            'ledger_posted': ledger_transaction is not None,
            'ledger_transaction_id': ledger_transaction.id if ledger_transaction else None,
            **PayrollRunSerializer.serialize(run),
        }

    @staticmethod
    def pay(tenant_id: int, run_id: str, *, actor_id=None, payment_reference=None, farm_id=None) -> dict:
        with unit_of_work():
            run = PayrollRunService.find(tenant_id, run_id, for_update=True)
            if run.status == PayrollRunStatus.PAID:
                PayrollRunService._post_ledger(run, actor_id=actor_id, farm_id=farm_id)
            elif run.status != PayrollRunStatus.FINALIZED:
                raise ApiError('CONFLICT', 'Payroll run must be finalized before payment.', 409)
            else:
                PayrollRunService._post_ledger(run, actor_id=actor_id, farm_id=farm_id)
                for item in run.line_items:
                    if item.advance_deduction:
                        EmployeeAdvanceService.stage_payroll_deduction(
                            tenant_id, item.staff_id, Decimal(str(item.advance_deduction)),
                            payroll_run=run, actor_id=_int_or_none(actor_id),
                        )
                run.status = PayrollRunStatus.PAID
                run.paid_at = datetime.now(timezone.utc)
                run.paid_by = _int_or_none(actor_id)
                if payment_reference:
                    run.notes = f'{run.notes or ""}\nPayment reference: {payment_reference}'.strip()
        return PayrollRunSerializer.serialize(run)

    @staticmethod
    def find(tenant_id: int, run_id: str, *, for_update: bool = False) -> PayrollRun:
        year, month = parse_period(run_id)
        run = PayrollRepository.get_run(tenant_id=tenant_id, payroll_year=year, payroll_month=month, for_update=for_update)
        if run is None:
            raise ApiError('NOT_FOUND', 'Payroll run not found.', 404)
        return run

    @staticmethod
    def _requested_period(data: dict) -> tuple[int, int]:
        year = data.get('payroll_year', data.get('payrollYear'))
        month = data.get('payroll_month', data.get('payrollMonth'))
        if year is None or month is None:
            raise ApiError('VALIDATION_ERROR', 'payroll_year and payroll_month are required.')
        try:
            year, month = int(year), int(month)
        except (TypeError, ValueError):
            raise ApiError('VALIDATION_ERROR', 'payroll_year and payroll_month must be integers.')
        if not 1 <= month <= 12:
            raise ApiError('VALIDATION_ERROR', 'payroll_month must be between 1 and 12.')
        return year, month

    @staticmethod
    def _existing(run: PayrollRun) -> dict:
        return {
            'message': 'Payroll run already exists.',
            'ledger_posted': run.status in {PayrollRunStatus.FINALIZED, PayrollRunStatus.PAID},
            **PayrollRunSerializer.serialize(run),
        }

    @staticmethod
    def _post_ledger(run: PayrollRun, *, actor_id=None, farm_id=None):
        """Posts (or finds) the run's ledger entries; a run with no farm can't be posted yet."""
        if run.farm_id is None:
            run.farm_id = farm_id
        if run.farm_id is None:
            return None
        if run.finalized_at is None:
            run.finalized_at = datetime.now(timezone.utc)
        return PayrollLedgerService.post_expense(run, actor_id=actor_id)

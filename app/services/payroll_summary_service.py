"""Payroll run history as one light list, and which period to run next."""
from __future__ import annotations

from app.models.hr import PayrollRunStatus
from app.repositories.hr_repo import PayrollRepository
from app.services.hr_serializers import PayrollRunSerializer, period_id
from app.utils.farm_time import farm_today


class PayrollSummaryService:
    @staticmethod
    def summary(tenant_id: int, *, limit: int = 24) -> dict:
        return {
            'next_period': PayrollSummaryService.next_period(tenant_id),
            'runs': [
                PayrollRunSerializer.serialize_summary_row(run, staff_count)
                for run, staff_count in PayrollRepository.list_run_summaries(tenant_id=tenant_id, limit=limit)
            ],
        }

    @staticmethod
    def next_period(tenant_id: int) -> dict:
        """The open draft's month; else the month after the latest run; else this month."""
        latest = PayrollRepository.latest_open_run(tenant_id=tenant_id)
        if latest is None:
            today = farm_today()
            year, month = today.year, today.month
        elif latest.status == PayrollRunStatus.DRAFT:
            year, month = latest.payroll_year, latest.payroll_month
        elif latest.payroll_month == 12:
            year, month = latest.payroll_year + 1, 1
        else:
            year, month = latest.payroll_year, latest.payroll_month + 1
        existing = PayrollRepository.get_run(tenant_id=tenant_id, payroll_year=year, payroll_month=month)
        return {
            'id': period_id(year, month),
            'payroll_year': year,
            'payroll_month': month,
            'existing_status': existing.status if existing else None,
        }

"""Posts salary advances to the ledger as wages paid early.

Payroll later expenses only the net pay, so an advance plus the payroll entry
add up to the full wage cost. Stages only; the caller commits.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from app.models.finance import CostClass, Transaction, TransactionCategory, TransactionStatus, TransactionType
from app.models.hr import Employee
from app.repositories.ledger_repo import TransactionRepository

SOURCE_DOCUMENT_TYPE = 'EMPLOYEE_ADVANCE'


class AdvanceLedgerService:
    @staticmethod
    def post_advance(employee: Employee, amount: Decimal, occurred_on: date, *,
                     actor_id: Optional[int], farm_id: Optional[int]) -> Transaction:
        now = datetime.now(timezone.utc)
        return TransactionRepository.stage(Transaction(
            tenant_id=employee.tenant_id,
            farm_id=farm_id,
            transaction_type=TransactionType.EXPENSE,
            category=TransactionCategory.LABOR_WAGES,
            cost_class=CostClass.COGS,
            amount=amount,
            item_name='Salary advance',
            description=f'Salary advance to {employee.full_name}',
            counterparty_name=employee.full_name[:120],
            timestamp=datetime.combine(occurred_on, now.timetz()),
            recorded_by=actor_id,
            status=TransactionStatus.POSTED.value,
            posted_at=now,
            posted_by=actor_id,
            source_document_type=SOURCE_DOCUMENT_TYPE,
            source_document_id=employee.id,
        ))

    @staticmethod
    def has_entries_for(employee: Employee) -> bool:
        return TransactionRepository.exists_for_source(employee.tenant_id, SOURCE_DOCUMENT_TYPE, employee.id)

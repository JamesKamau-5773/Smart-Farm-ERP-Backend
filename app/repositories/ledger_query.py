"""The one filter builder for ledger queries.

The list endpoint, its KPI cards and every period total apply exactly this, so
a filter can never change one of them without changing the others.
"""
from __future__ import annotations

from sqlalchemy import or_

from app.models.finance import Transaction
from app.schemas.ledger_filters import LedgerFilters
from app.services.ledger_account_scope import AccountScope
from app.services.period_resolver import DateRange
from app.services.request_scope import FarmScope
from app.utils.farm_time import local_date_sql


def ledger_local_date():
    """Farm-local calendar date of a ledger entry (matches ix_transactions_tenant_farm_local_date)."""
    return local_date_sql(Transaction.timestamp)


def apply_ledger_filters(query, scope: FarmScope, filters: LedgerFilters, accounts: AccountScope,
                         date_range: DateRange | None = None):
    query = query.filter(Transaction.tenant_id == scope.tenant_id)
    if scope.farm_id is not None:
        query = query.filter(Transaction.farm_id == scope.farm_id)

    local_date = ledger_local_date()
    if filters.date_from is not None:
        query = query.filter(local_date >= filters.date_from)
    if filters.date_to is not None:
        query = query.filter(local_date <= filters.date_to)
    if date_range is not None:
        query = query.filter(local_date >= date_range.start, local_date <= date_range.end)

    if filters.types is not None:
        query = query.filter(Transaction.transaction_type.in_(filters.types))
    if filters.category is not None:
        query = query.filter(or_(
            Transaction.category == filters.category,
            Transaction.income_category == filters.category.value,
        ))

    if accounts.is_narrowed:
        predicates = []
        if accounts.customer_ids:
            predicates.append(Transaction.customer_id.in_(accounts.customer_ids))
        if accounts.buyer_ids:
            predicates.append(Transaction.buyer_id.in_(accounts.buyer_ids))
        query = query.filter(or_(*predicates)) if predicates else query.filter(False)
    return query

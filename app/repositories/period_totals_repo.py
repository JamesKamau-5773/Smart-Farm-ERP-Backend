"""Aggregation queries for the period totals. Grouping happens in SQL.

Rows are grouped on the farm-local date truncated to each level
(``date_trunc`` on the local date: ISO weeks start on Monday in PostgreSQL), and
optionally on the parent level too, so a week that spans two months is split
between them. Callers turn the returned bucket start dates into keys with the
period resolver, so key formatting lives in exactly one place.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, cast, func, tuple_

from app import db
from app.models.finance import Transaction
from app.models.supply import MilkDisposition, MilkDispositionType, MilkLog
from app.repositories.ledger_query import apply_ledger_filters, ledger_local_date
from app.repositories.production_query import apply_production_filters, milk_local_date
from app.schemas.ledger_filters import LedgerFilters
from app.schemas.production_filters import ProductionFilters
from app.services import ledger_classification
from app.services.ledger_account_scope import AccountScope
from app.services.ledger_classification import LedgerBucket
from app.services.period_amounts import LedgerAmounts, ProductionAmounts
from app.services.period_resolver import DateRange, Level
from app.services.request_scope import FarmScope


def _truncate(level: Level, local_date):
    if level == Level.DAY:
        return local_date
    return cast(func.date_trunc(level.value, cast(local_date, DateTime)), Date)


def _decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _as_date(value) -> date:
    return value.date() if isinstance(value, datetime) else value


def _grouped(query, local_date, group_levels: tuple[Level, ...]):
    """Add GROUP BY columns for ``group_levels``; returns (query, number of key columns)."""
    columns = [_truncate(level, local_date).label(f'k_{level.value}') for level in group_levels]
    if columns:
        query = query.add_columns(*columns).group_by(*columns)
    return query, len(columns)


def _split(row, key_count: int):
    values = tuple(row)
    keys = tuple(_as_date(value) for value in values[len(values) - key_count:]) if key_count else ()
    return keys, values[:len(values) - key_count] if key_count else values


class LedgerTotalsRepository:
    @staticmethod
    def aggregate(scope: FarmScope, filters: LedgerFilters, accounts: AccountScope, *,
                  date_range: DateRange | None = None,
                  group_levels: tuple[Level, ...] = ()) -> list[tuple[tuple[date, ...], LedgerAmounts]]:
        query = db.session.query(
            ledger_classification.bucket_sum(LedgerBucket.INCOME),
            ledger_classification.bucket_sum(LedgerBucket.EXPENSE),
            ledger_classification.bucket_sum(LedgerBucket.UNPAID),
            ledger_classification.bucket_sum(LedgerBucket.CREDIT),
            func.count(Transaction.id),
        ).select_from(Transaction)
        query = apply_ledger_filters(query, scope, filters, accounts, date_range)
        query, key_count = _grouped(query, ledger_local_date(), group_levels)
        results = []
        for row in query.all():
            keys, (income, expenses, unpaid, credit, count) = _split(row, key_count)
            results.append((keys, LedgerAmounts(
                income=_decimal(income), expenses=_decimal(expenses), unpaid=_decimal(unpaid), credit=_decimal(credit), count=int(count or 0),
            )))
        return results

    @classmethod
    def totals(cls, scope: FarmScope, filters: LedgerFilters, accounts: AccountScope, *,
               date_range: DateRange | None = None) -> LedgerAmounts:
        rows = cls.aggregate(scope, filters, accounts, date_range=date_range)
        return rows[0][1] if rows else LedgerAmounts()


class ProductionTotalsRepository:
    @staticmethod
    def aggregate(scope: FarmScope, filters: ProductionFilters, *,
                  date_range: DateRange | None = None,
                  group_levels: tuple[Level, ...] = ()) -> list[tuple[tuple[date, ...], ProductionAmounts]]:
        local_date = milk_local_date()
        query = db.session.query(
            func.coalesce(func.sum(MilkLog.amount_liters), 0),
            func.count(MilkLog.id),
            func.count(func.distinct(local_date)),
            func.count(func.distinct(tuple_(MilkLog.cow_id, local_date))),
        ).select_from(MilkLog)
        query = apply_production_filters(query, scope, filters, date_range)
        query, key_count = _grouped(query, local_date, group_levels)
        results = []
        for row in query.all():
            keys, (litres, entries, milking_days, cow_days) = _split(row, key_count)
            results.append((keys, ProductionAmounts(
                litres=_decimal(litres), entries=int(entries or 0),
                milking_days=int(milking_days or 0), cow_days=int(cow_days or 0),
            )))
        return results

    @staticmethod
    def fed_to_calves(scope: FarmScope, filters: ProductionFilters, date_range: DateRange) -> Decimal | None:
        """Litres fed to calves in the range, or None when the filters select particular milkings."""
        if filters.narrows_to_milkings:
            return None
        query = db.session.query(func.coalesce(func.sum(MilkDisposition.liters), 0)).filter(
            MilkDisposition.tenant_id == scope.tenant_id,
            MilkDisposition.disposition_type == MilkDispositionType.CALF_FEED,
            MilkDisposition.disposition_date >= date_range.start,
            MilkDisposition.disposition_date <= date_range.end,
        )
        if filters.date_from is not None:
            query = query.filter(MilkDisposition.disposition_date >= filters.date_from)
        if filters.date_to is not None:
            query = query.filter(MilkDisposition.disposition_date <= filters.date_to)
        return _decimal(query.scalar())

    @staticmethod
    def last_entry_date(scope: FarmScope, filters: ProductionFilters) -> date | None:
        """Farm-local date of the newest matching milking, ignoring any date filters."""
        local_date = milk_local_date()
        query = db.session.query(func.max(local_date)).select_from(MilkLog)
        query = apply_production_filters(query, scope, replace(filters, date_from=None, date_to=None))
        value = query.scalar()
        return _as_date(value) if value is not None else None

    @classmethod
    def totals(cls, scope: FarmScope, filters: ProductionFilters, *,
               date_range: DateRange | None = None) -> ProductionAmounts:
        rows = cls.aggregate(scope, filters, date_range=date_range)
        return rows[0][1] if rows else ProductionAmounts()

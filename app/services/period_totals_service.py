"""Period summaries and group totals for the ledger and milk production.

Each service composes the period resolver (calendar maths) with its totals
repository (SQL aggregation) and computes the period-over-period change. They
return domain values (Decimal / int); serializers format them for the API.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Generic, TypeVar

from app.repositories.period_totals_repo import LedgerTotalsRepository, ProductionTotalsRepository
from app.schemas.ledger_filters import LedgerFilters
from app.schemas.period_query import PeriodQuery
from app.schemas.production_filters import ProductionFilters
from app.services import period_resolver
from app.services.ledger_account_scope import AccountScope, LedgerAccountScopeResolver
from app.services.period_amounts import LedgerAmounts, ProductionAmounts
from app.services.period_resolver import Bucket, DateRange, Level, Period, ResolvedPeriod
from app.services.request_scope import FarmScope
from app.utils.farm_time import farm_today

Amounts = TypeVar('Amounts', LedgerAmounts, ProductionAmounts)


@dataclass(frozen=True)
class Change:
    absolute: Decimal
    percent: Decimal | None  # None when the previous value is zero


@dataclass(frozen=True)
class PeriodSummary(Generic[Amounts]):
    period: ResolvedPeriod
    current: Amounts
    previous: Amounts
    change: Change
    breakdown: tuple[tuple[Bucket, Amounts], ...]
    last_entry_date: date | None = None


@dataclass(frozen=True)
class GroupTotal(Generic[Amounts]):
    level: Level
    key: str
    parent: str | None
    label: str
    amounts: Amounts


@dataclass(frozen=True)
class ProductionChange(Change):
    """Litres change plus the percent change of each other summary metric (None when not comparable)."""
    avg_litres_per_day_percent: Decimal | None = None
    entries_percent: Decimal | None = None
    fed_to_calves_percent: Decimal | None = None
    available_percent: Decimal | None = None


def percent_change(current: Decimal, previous: Decimal) -> Change:
    absolute = current - previous
    percent = absolute * 100 / abs(previous) if previous else None
    return Change(absolute=absolute, percent=percent)


def percent_or_none(current, previous) -> Decimal | None:
    if current is None or previous is None:
        return None
    return percent_change(Decimal(current), Decimal(previous)).percent


class PeriodTotalsService(ABC, Generic[Amounts]):
    """Shared summary / group-totals algorithm; subclasses supply the data."""

    #: Which bucket level a summary of each period is broken down into.
    BREAKDOWN_LEVELS: dict[Period, Level]

    # --- hooks ----------------------------------------------------------------

    @abstractmethod
    def _context(self, scope: FarmScope, filters) -> Any:
        """Anything the repository needs, resolved once per request."""

    @abstractmethod
    def _aggregate(self, context, *, date_range: DateRange | None = None,
                   group_levels: tuple[Level, ...] = ()) -> list[tuple[tuple[date, ...], Amounts]]:
        ...

    @abstractmethod
    def _empty(self) -> Amounts:
        ...

    @abstractmethod
    def _change(self, current: Amounts, previous: Amounts) -> Change:
        ...

    def _last_entry_date(self, context) -> date | None:
        return None

    # --- algorithm ------------------------------------------------------------

    def _total(self, context, date_range: DateRange) -> Amounts:
        rows = self._aggregate(context, date_range=date_range)
        return rows[0][1] if rows else self._empty()

    def summary(self, scope: FarmScope, query: PeriodQuery, filters, *, today: date | None = None) -> PeriodSummary[Amounts]:
        resolved = period_resolver.resolve(
            query.period,
            query.anchor,
            breakdown_level=self.BREAKDOWN_LEVELS[query.period],
            today=today or farm_today(),
        )
        context = self._context(scope, filters)
        current = self._total(context, resolved.range)
        previous = self._total(context, resolved.previous.range)

        rows = self._aggregate(context, date_range=resolved.range, group_levels=(resolved.breakdown_level,))
        by_start = {keys[0]: amounts for keys, amounts in rows}
        breakdown = tuple((bucket, by_start.get(bucket.range.start, self._empty())) for bucket in resolved.breakdown)

        return PeriodSummary(
            period=resolved,
            current=current,
            previous=previous,
            change=self._change(current, previous),
            breakdown=breakdown,
            last_entry_date=self._last_entry_date(context),
        )

    def group_totals(self, scope: FarmScope, filters, levels: tuple[Level, ...]) -> list[GroupTotal[Amounts]]:
        context = self._context(scope, filters)
        groups: list[tuple[tuple, GroupTotal]] = []
        for level in levels:
            parent = period_resolver.parent_level(level, levels)
            group_levels = (parent, level) if parent else (level,)
            for keys, amounts in self._aggregate(context, group_levels=group_levels):
                start = keys[-1]
                parent_start = keys[0] if parent else None
                groups.append((
                    (period_resolver.LEVEL_ORDER.index(level), parent_start or start, start),
                    GroupTotal(
                        level=level,
                        key=period_resolver.bucket_key(level, start),
                        parent=period_resolver.bucket_key(parent, parent_start) if parent else None,
                        label=period_resolver.group_label(level, start),
                        amounts=amounts,
                    ),
                ))
        # Coarsest level first; newest first within a level.
        groups.sort(key=lambda item: (item[0][0], _descending(item[0][1]), _descending(item[0][2])))
        return [group for _, group in groups]


def _descending(value: date) -> int:
    return -value.toordinal()


@dataclass(frozen=True)
class _LedgerContext:
    scope: FarmScope
    filters: LedgerFilters
    accounts: AccountScope


class LedgerTotalsService(PeriodTotalsService[LedgerAmounts]):
    BREAKDOWN_LEVELS = {Period.YEAR: Level.MONTH, Period.MONTH: Level.WEEK, Period.WEEK: Level.DAY}

    def _context(self, scope: FarmScope, filters: LedgerFilters) -> _LedgerContext:
        return _LedgerContext(scope, filters, LedgerAccountScopeResolver.resolve(scope, filters))

    def _aggregate(self, context: _LedgerContext, *, date_range=None, group_levels=()):
        return LedgerTotalsRepository.aggregate(
            context.scope, context.filters, context.accounts, date_range=date_range, group_levels=group_levels,
        )

    def _empty(self) -> LedgerAmounts:
        return LedgerAmounts()

    def _change(self, current: LedgerAmounts, previous: LedgerAmounts) -> Change:
        return percent_change(current.net, previous.net)


@dataclass(frozen=True)
class _ProductionContext:
    scope: FarmScope
    filters: ProductionFilters


class ProductionTotalsService(PeriodTotalsService[ProductionAmounts]):
    BREAKDOWN_LEVELS = {Period.YEAR: Level.MONTH, Period.MONTH: Level.DAY, Period.WEEK: Level.DAY}

    def _context(self, scope: FarmScope, filters: ProductionFilters) -> _ProductionContext:
        return _ProductionContext(scope, filters)

    def _aggregate(self, context: _ProductionContext, *, date_range=None, group_levels=()):
        return ProductionTotalsRepository.aggregate(
            context.scope, context.filters, date_range=date_range, group_levels=group_levels,
        )

    def _empty(self) -> ProductionAmounts:
        return ProductionAmounts()

    def _total(self, context: _ProductionContext, date_range: DateRange) -> ProductionAmounts:
        amounts = super()._total(context, date_range)
        fed = ProductionTotalsRepository.fed_to_calves(context.scope, context.filters, date_range)
        return replace(amounts, fed_to_calves=fed)

    def _change(self, current: ProductionAmounts, previous: ProductionAmounts) -> ProductionChange:
        litres = percent_change(current.litres, previous.litres)
        return ProductionChange(
            absolute=litres.absolute,
            percent=litres.percent,
            avg_litres_per_day_percent=percent_or_none(current.avg_litres_per_day, previous.avg_litres_per_day),
            entries_percent=percent_or_none(current.entries, previous.entries),
            fed_to_calves_percent=percent_or_none(current.fed_to_calves, previous.fed_to_calves),
            available_percent=percent_or_none(current.available, previous.available),
        )

    def _last_entry_date(self, context: _ProductionContext) -> date | None:
        return ProductionTotalsRepository.last_entry_date(context.scope, context.filters)

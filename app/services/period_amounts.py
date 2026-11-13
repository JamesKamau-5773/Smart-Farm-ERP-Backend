"""Value objects for aggregated totals. Decimal only, never float."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal('0')


@dataclass(frozen=True)
class LedgerAmounts:
    income: Decimal = ZERO
    expenses: Decimal = ZERO
    unpaid: Decimal = ZERO
    credit: Decimal = ZERO
    count: int = 0

    @property
    def net(self) -> Decimal:
        return self.income - self.expenses


@dataclass(frozen=True)
class ProductionAmounts:
    litres: Decimal = ZERO
    entries: int = 0
    milking_days: int = 0
    cow_days: int = 0
    # Period totals only; None when it can't be matched to the filters (see ProductionFilters).
    fed_to_calves: Decimal | None = None

    @property
    def available(self) -> Decimal | None:
        return self.litres - self.fed_to_calves if self.fed_to_calves is not None else None

    @property
    def avg_litres_per_day(self) -> Decimal | None:
        return self.litres / self.milking_days if self.milking_days else None

    @property
    def avg_litres_per_cow_day(self) -> Decimal | None:
        return self.litres / self.cow_days if self.cow_days else None

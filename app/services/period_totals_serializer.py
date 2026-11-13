"""API formatting for period totals (contract: docs/contracts/period-totals.md).

Money is an integer count of minor units (cents) as a string, litres are
1-decimal-place strings and percentages are 1-decimal-place strings. Values
stay Decimal until they become strings here; floats are never used.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.services.period_amounts import LedgerAmounts, ProductionAmounts
from app.services.period_resolver import Bucket, DateRange
from app.services.period_totals_service import Change, GroupTotal, PeriodSummary, ProductionChange

ONE = Decimal('1')
TENTH = Decimal('0.1')


def money(value: Decimal) -> str:
    """KES 27,005.00 -> "2700500"."""
    return str(int((Decimal(value) * 100).quantize(ONE, rounding=ROUND_HALF_UP)))


def one_dp(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rounded = Decimal(value).quantize(TENTH, rounding=ROUND_HALF_UP)
    return str(rounded + 0)  # "+ 0" turns "-0.0" into "0.0"


def litres(value: Decimal | None) -> str:
    return one_dp(value if value is not None else Decimal('0'))


def date_range(range_: DateRange) -> dict:
    return {'from': range_.start.isoformat(), 'to': range_.end.isoformat()}


class _PeriodTotalsSerializer:
    """Shared summary/groups envelope; subclasses format their own amounts."""

    def current(self, amounts) -> dict:
        raise NotImplementedError

    def change(self, change: Change) -> dict:
        raise NotImplementedError

    def breakdown_item(self, bucket: Bucket, amounts) -> dict:
        raise NotImplementedError

    def group_amounts(self, amounts) -> dict:
        raise NotImplementedError

    def summary(self, result: PeriodSummary) -> dict:
        period = result.period
        return {
            'period': period.period.value,
            'key': period.key,
            'label': period.label,
            'range': date_range(period.range),
            'has_next': period.has_next,
            'current': self.current(result.current),
            'previous': {
                'key': period.previous.key,
                'label': period.previous.label,
                **self.current(result.previous),
            },
            'change': self.change(result.change),
            'breakdown': [self.breakdown_item(bucket, amounts) for bucket, amounts in result.breakdown],
        }

    def groups(self, groups: list[GroupTotal]) -> dict:
        items = []
        for group in groups:
            item = {'level': group.level.value, 'key': group.key}
            if group.parent is not None:
                item['parent'] = group.parent
            item['label'] = group.label
            item.update(self.group_amounts(group.amounts))
            items.append(item)
        return {'groups': items}


class LedgerTotalsSerializer(_PeriodTotalsSerializer):
    def current(self, amounts: LedgerAmounts) -> dict:
        return {
            'income': money(amounts.income),
            'expenses': money(amounts.expenses),
            'net': money(amounts.net),
            'unpaid': money(amounts.unpaid),
            'credit': money(amounts.credit),
            'count': amounts.count,
        }

    def change(self, change: Change) -> dict:
        return {'net_abs': money(change.absolute), 'net_pct': one_dp(change.percent)}

    def breakdown_item(self, bucket: Bucket, amounts: LedgerAmounts) -> dict:
        return {
            'key': bucket.key,
            'label': bucket.label,
            'income': money(amounts.income),
            'expenses': money(amounts.expenses),
            'net': money(amounts.net),
        }

    def group_amounts(self, amounts: LedgerAmounts) -> dict:
        return {
            'count': amounts.count,
            'income': money(amounts.income),
            'expenses': money(amounts.expenses),
            'net': money(amounts.net),
            'unpaid': money(amounts.unpaid),
            'credit': money(amounts.credit),
        }


class ProductionTotalsSerializer(_PeriodTotalsSerializer):
    def current(self, amounts: ProductionAmounts) -> dict:
        return {
            'litres': litres(amounts.litres),
            'entries': amounts.entries,
            'milking_days': amounts.milking_days,
            'avg_litres_per_day': litres(amounts.avg_litres_per_day),
            'avg_litres_per_cow_day': litres(amounts.avg_litres_per_cow_day),
            # null, not "0.0", when a cow/session/anomaly filter means calf feedings can't be matched.
            'fed_to_calves_litres': one_dp(amounts.fed_to_calves),
            'available_litres': one_dp(amounts.available),
        }

    def change(self, change: ProductionChange) -> dict:
        return {
            'litres_abs': litres(change.absolute),
            'litres_pct': one_dp(change.percent),
            'avg_litres_per_day_pct': one_dp(change.avg_litres_per_day_percent),
            'entries_pct': one_dp(change.entries_percent),
            'fed_to_calves_pct': one_dp(change.fed_to_calves_percent),
            'available_pct': one_dp(change.available_percent),
        }

    def summary(self, result: PeriodSummary) -> dict:
        body = super().summary(result)
        last_entry = result.last_entry_date
        body['current']['last_entry_date'] = last_entry.isoformat() if last_entry else None
        return body

    def breakdown_item(self, bucket: Bucket, amounts: ProductionAmounts) -> dict:
        return {'key': bucket.key, 'label': bucket.label, 'litres': litres(amounts.litres)}

    def group_amounts(self, amounts: ProductionAmounts) -> dict:
        return {
            'litres': litres(amounts.litres),
            'entries': amounts.entries,
            'avg_litres_per_day': litres(amounts.avg_litres_per_day),
        }

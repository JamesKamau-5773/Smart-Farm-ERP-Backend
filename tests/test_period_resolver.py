"""Pure unit tests for the period resolver, query schema and serializers (no database)."""
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.datastructures import MultiDict

from app.schemas.period_query import GroupLevelsQuery, PeriodQuery
from app.services import period_resolver as pr
from app.services.period_resolver import DateRange, Level, Period
from app.services.period_totals_serializer import litres, money, one_dp
from app.utils.api_errors import ApiError

TODAY = date(2026, 11, 6)  # a Friday in ISO week 2026-W45


# --- weeks --------------------------------------------------------------------

@pytest.mark.parametrize('anchor', [date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 8)])
def test_week_runs_monday_to_sunday(anchor):
    resolved = pr.resolve(Period.WEEK, anchor, breakdown_level=Level.DAY, today=TODAY)
    assert resolved.range == DateRange(date(2026, 11, 2), date(2026, 11, 8))
    assert resolved.key == '2026-W45'
    assert resolved.label == '2 – 8 Nov 2026'
    assert [bucket.key for bucket in resolved.breakdown] == [f'2026-11-0{day}' for day in range(2, 9)]
    assert resolved.breakdown[0].label == 'Mon 2'


def test_week_spanning_two_months():
    resolved = pr.resolve(Period.WEEK, date(2026, 10, 29), breakdown_level=Level.DAY, today=TODAY)
    assert resolved.range == DateRange(date(2026, 10, 26), date(2026, 11, 1))
    assert resolved.key == '2026-W44'
    assert resolved.label == '26 Oct – 1 Nov 2026'
    assert pr.bucket_key(Level.MONTH, resolved.range.start) == '2026-10'
    assert pr.bucket_key(Level.MONTH, resolved.range.end) == '2026-11'


def test_month_breakdown_includes_partial_edge_weeks():
    resolved = pr.resolve(Period.MONTH, date(2026, 11, 15), breakdown_level=Level.WEEK, today=TODAY)
    keys = [bucket.key for bucket in resolved.breakdown]
    assert keys == ['2026-W44', '2026-W45', '2026-W46', '2026-W47', '2026-W48', '2026-W49']
    assert resolved.breakdown[0].label == '26 Oct – 1 Nov'
    assert resolved.breakdown[-1].label == '30 Nov – 6 Dec'


def test_iso_week_at_year_boundaries():
    # 1 Jan 2026 is a Thursday, so ISO week 1 of 2026 starts on 29 Dec 2025.
    assert pr.bucket_key(Level.WEEK, date(2025, 12, 29)) == '2026-W01'
    assert pr.bucket_range(Level.WEEK, date(2026, 1, 1)) == DateRange(date(2025, 12, 29), date(2026, 1, 4))
    assert pr.week_label(pr.bucket_range(Level.WEEK, date(2026, 1, 1))) == '29 Dec 2025 – 4 Jan 2026'
    # 2026 has 53 ISO weeks; 1 Jan 2027 (a Friday) is still in 2026-W53.
    assert pr.bucket_key(Level.WEEK, date(2027, 1, 1)) == '2026-W53'
    assert pr.bucket_key(Level.WEEK, date(2027, 1, 4)) == '2027-W01'


def test_previous_period_crosses_year_boundary():
    month = pr.resolve(Period.MONTH, date(2026, 1, 10), breakdown_level=Level.DAY, today=TODAY)
    assert (month.previous.key, month.previous.label) == ('2025-12', 'Dec 2025')
    assert month.previous.range == DateRange(date(2025, 12, 1), date(2025, 12, 31))

    week = pr.resolve(Period.WEEK, date(2026, 1, 2), breakdown_level=Level.DAY, today=TODAY)
    assert week.key == '2026-W01'
    assert week.previous.key == '2025-W52'

    year = pr.resolve(Period.YEAR, date(2026, 6, 1), breakdown_level=Level.MONTH, today=TODAY)
    assert year.range == DateRange(date(2026, 1, 1), date(2026, 12, 31))
    assert year.previous.key == '2025'
    assert [bucket.label for bucket in year.breakdown][:2] == ['Jan', 'Feb']
    assert len(year.breakdown) == 12


# --- leap years -----------------------------------------------------------------

def test_leap_year_february():
    leap = pr.resolve(Period.MONTH, date(2028, 2, 10), breakdown_level=Level.DAY, today=TODAY)
    assert leap.range == DateRange(date(2028, 2, 1), date(2028, 2, 29))
    assert len(leap.breakdown) == 29
    assert leap.breakdown[-1].key == '2028-02-29'

    common = pr.resolve(Period.MONTH, date(2026, 2, 10), breakdown_level=Level.DAY, today=TODAY)
    assert common.range.end == date(2026, 2, 28)

    march = pr.resolve(Period.MONTH, date(2028, 3, 1), breakdown_level=Level.DAY, today=TODAY)
    assert march.previous.range == DateRange(date(2028, 2, 1), date(2028, 2, 29))


def test_leap_day_week_and_year():
    assert pr.bucket_keys(date(2028, 2, 29)) == {
        'year': '2028', 'month': '2028-02', 'week': '2028-W09', 'day': '2028-02-29',
    }
    assert pr.bucket_range(Level.YEAR, date(2028, 2, 29)) == DateRange(date(2028, 1, 1), date(2028, 12, 31))


# --- has_next / validation ------------------------------------------------------------

def test_has_next_only_for_past_periods():
    assert pr.resolve(Period.MONTH, TODAY, breakdown_level=Level.WEEK, today=TODAY).has_next is False
    assert pr.resolve(Period.MONTH, date(2026, 10, 1), breakdown_level=Level.WEEK, today=TODAY).has_next is True
    assert pr.resolve(Period.WEEK, TODAY, breakdown_level=Level.DAY, today=TODAY).has_next is False


def test_resolve_rejects_breakdown_not_finer_than_period():
    with pytest.raises(ValueError):
        pr.resolve(Period.WEEK, TODAY, breakdown_level=Level.MONTH, today=TODAY)


def test_parent_level_is_nearest_requested_coarser_level():
    assert pr.parent_level(Level.DAY, (Level.YEAR, Level.WEEK, Level.DAY)) == Level.WEEK
    assert pr.parent_level(Level.WEEK, (Level.YEAR, Level.WEEK)) == Level.YEAR
    assert pr.parent_level(Level.YEAR, (Level.YEAR, Level.DAY)) is None


def test_group_labels():
    assert pr.group_label(Level.YEAR, date(2026, 1, 1)) == '2026'
    assert pr.group_label(Level.MONTH, date(2026, 11, 1)) == 'November'
    assert pr.group_label(Level.WEEK, date(2026, 11, 2)) == '2 – 8 Nov'
    assert pr.group_label(Level.DAY, date(2026, 11, 6)) == 'Nov 06, 2026'


@pytest.mark.parametrize('args', [{'period': 'decade'}, {'period': 'day'}])
def test_period_query_rejects_unknown_period(args):
    with pytest.raises(ApiError) as error:
        PeriodQuery.from_args(MultiDict(args), today=TODAY)
    assert error.value.status == 422
    assert error.value.code == 'INVALID_PERIOD'


@pytest.mark.parametrize('anchor', ['2026-13-01', '2026-02-30', 'yesterday', '20261106', '2026-11-06T10:00'])
def test_period_query_rejects_invalid_anchor(anchor):
    with pytest.raises(ApiError) as error:
        PeriodQuery.from_args(MultiDict({'period': 'month', 'anchor': anchor}), today=TODAY)
    assert error.value.status == 422
    assert error.value.code == 'INVALID_ANCHOR'


def test_period_query_defaults():
    query = PeriodQuery.from_args(MultiDict(), today=TODAY)
    assert (query.period, query.anchor) == (Period.MONTH, TODAY)


def test_group_levels_query():
    assert GroupLevelsQuery.from_args(MultiDict({'levels': 'day,year'})).levels == (Level.YEAR, Level.DAY)
    with pytest.raises(ApiError) as error:
        GroupLevelsQuery.from_args(MultiDict({'levels': 'year,century'}))
    assert error.value.status == 422


# --- serializer formatting -------------------------------------------------------------

def test_money_is_integer_minor_units():
    assert money(Decimal('27005.00')) == '2700500'
    assert money(Decimal('-800.00')) == '-80000'
    assert money(Decimal('0')) == '0'
    assert money(Decimal('0.005')) == '1'


def test_litres_and_percent_are_one_decimal_place():
    assert litres(Decimal('246')) == '246.0'
    assert litres(Decimal('17.75')) == '17.8'
    assert litres(None) == '0.0'
    assert one_dp(Decimal('-0.04')) == '0.0'
    assert one_dp(None) is None

"""Pure calendar maths for period totals: ranges, keys, labels and breakdowns.

No database access and no clock: callers pass ``today`` (the farm-local date).
Weeks are ISO weeks starting on Monday. All dates are farm-local calendar dates.

Bucket keys are the contract's: year ``2026``, month ``2026-11``,
week ``2026-W45`` (ISO week-year), day ``2026-11-06``.
"""
from __future__ import annotations

import calendar
import enum
from dataclasses import dataclass
from datetime import date, timedelta


class Level(str, enum.Enum):
    YEAR = 'year'
    MONTH = 'month'
    WEEK = 'week'
    DAY = 'day'


class Period(str, enum.Enum):
    """The spans a summary can cover; each one is also a bucket level."""
    WEEK = 'week'
    MONTH = 'month'
    YEAR = 'year'

    @property
    def level(self) -> Level:
        return Level(self.value)


# Coarsest first; used to find a level's parent.
LEVEL_ORDER = (Level.YEAR, Level.MONTH, Level.WEEK, Level.DAY)


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date  # inclusive

    def __post_init__(self):
        if self.end < self.start:
            raise ValueError('DateRange end is before start.')

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end

    def intersect(self, other: 'DateRange') -> 'DateRange | None':
        start, end = max(self.start, other.start), min(self.end, other.end)
        return DateRange(start, end) if start <= end else None


@dataclass(frozen=True)
class Bucket:
    level: Level
    key: str
    label: str
    range: DateRange


@dataclass(frozen=True)
class ResolvedPeriod:
    period: Period
    key: str
    label: str
    range: DateRange
    previous: Bucket
    breakdown_level: Level
    breakdown: tuple[Bucket, ...]
    has_next: bool


# --- Bucket start / range -------------------------------------------------

def bucket_start(level: Level, value: date) -> date:
    """First day of the bucket at ``level`` that contains ``value``."""
    if level == Level.YEAR:
        return date(value.year, 1, 1)
    if level == Level.MONTH:
        return value.replace(day=1)
    if level == Level.WEEK:
        return value - timedelta(days=value.weekday())
    return value


def bucket_range(level: Level, value: date) -> DateRange:
    start = bucket_start(level, value)
    if level == Level.YEAR:
        return DateRange(start, date(start.year, 12, 31))
    if level == Level.MONTH:
        return DateRange(start, start.replace(day=calendar.monthrange(start.year, start.month)[1]))
    if level == Level.WEEK:
        return DateRange(start, start + timedelta(days=6))
    return DateRange(start, start)


def next_bucket_start(level: Level, value: date) -> date:
    return bucket_range(level, value).end + timedelta(days=1)


def previous_bucket_start(level: Level, value: date) -> date:
    return bucket_start(level, bucket_start(level, value) - timedelta(days=1))


# --- Keys -------------------------------------------------------------------

def bucket_key(level: Level, value: date) -> str:
    if level == Level.YEAR:
        return f'{value.year:04d}'
    if level == Level.MONTH:
        return f'{value.year:04d}-{value.month:02d}'
    if level == Level.WEEK:
        iso_year, iso_week, _ = value.isocalendar()
        return f'{iso_year:04d}-W{iso_week:02d}'
    return value.isoformat()


def bucket_keys(value: date | None) -> dict | None:
    """The ``bucket`` object attached to list records."""
    if value is None:
        return None
    return {level.value: bucket_key(level, value) for level in LEVEL_ORDER}


# --- Labels -----------------------------------------------------------------

def _day_month(value: date) -> str:
    return f'{value.day} {value.strftime("%b")}'


def week_label(range_: DateRange, *, with_year: bool = False) -> str:
    """``2 – 8 Nov``, ``26 Oct – 1 Nov``, ``29 Dec 2025 – 4 Jan 2026``."""
    start, end = range_.start, range_.end
    if start.year != end.year:
        return f'{_day_month(start)} {start.year} – {_day_month(end)} {end.year}'
    suffix = f' {end.year}' if with_year else ''
    if start.month == end.month:
        return f'{start.day} – {_day_month(end)}{suffix}'
    return f'{_day_month(start)} – {_day_month(end)}{suffix}'


def period_label(level: Level, value: date) -> str:
    """Heading for a whole summary period: ``2026``, ``Nov 2026``, ``2 – 8 Nov 2026``."""
    if level == Level.YEAR:
        return f'{value.year}'
    if level == Level.MONTH:
        return f'{value.strftime("%b")} {value.year}'
    if level == Level.WEEK:
        return week_label(bucket_range(Level.WEEK, value), with_year=True)
    return f'{value.strftime("%a")} {_day_month(value)} {value.year}'


def breakdown_label(level: Level, value: date) -> str:
    """Short chart label inside a summary: ``Jan``, ``2 – 8 Nov``, ``Sun 1``."""
    if level == Level.MONTH:
        return value.strftime('%b')
    if level == Level.WEEK:
        return week_label(bucket_range(Level.WEEK, value))
    if level == Level.DAY:
        return f'{value.strftime("%a")} {value.day}'
    return f'{value.year}'


def group_label(level: Level, value: date) -> str:
    """List group header: ``2026``, ``November``, ``2 – 8 Nov``, ``Nov 06, 2026``."""
    if level == Level.YEAR:
        return f'{value.year}'
    if level == Level.MONTH:
        return value.strftime('%B')
    if level == Level.WEEK:
        return week_label(bucket_range(Level.WEEK, value))
    return value.strftime('%b %d, %Y')


# --- Composition --------------------------------------------------------------

def make_bucket(level: Level, value: date, *, label_style=breakdown_label) -> Bucket:
    start = bucket_start(level, value)
    return Bucket(level=level, key=bucket_key(level, start), label=label_style(level, start), range=bucket_range(level, start))


def iter_buckets(level: Level, range_: DateRange, *, label_style=breakdown_label) -> tuple[Bucket, ...]:
    """Every ``level`` bucket that overlaps ``range_``, oldest first."""
    buckets = []
    cursor = bucket_start(level, range_.start)
    while cursor <= range_.end:
        buckets.append(make_bucket(level, cursor, label_style=label_style))
        cursor = next_bucket_start(level, cursor)
    return tuple(buckets)


def parent_level(level: Level, levels) -> Level | None:
    """Nearest coarser level among ``levels``, if any."""
    index = LEVEL_ORDER.index(level)
    for candidate in reversed(LEVEL_ORDER[:index]):
        if candidate in levels:
            return candidate
    return None


def resolve(period: Period, anchor: date, *, breakdown_level: Level, today: date) -> ResolvedPeriod:
    level = period.level
    if LEVEL_ORDER.index(breakdown_level) <= LEVEL_ORDER.index(level):
        raise ValueError('breakdown_level must be finer than the period.')
    start = bucket_start(level, anchor)
    range_ = bucket_range(level, start)
    previous_start = previous_bucket_start(level, start)
    previous = Bucket(
        level=level,
        key=bucket_key(level, previous_start),
        label=period_label(level, previous_start),
        range=bucket_range(level, previous_start),
    )
    return ResolvedPeriod(
        period=period,
        key=bucket_key(level, start),
        label=period_label(level, start),
        range=range_,
        previous=previous,
        breakdown_level=breakdown_level,
        breakdown=iter_buckets(breakdown_level, range_),
        has_next=next_bucket_start(level, start) <= today,
    )

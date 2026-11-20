"""Farm-local calendar dates.

Records such as "mixed on" and "fed on" are calendar dates as the farmer sees
them. Deriving them from UTC puts anything recorded between midnight and 03:00
East Africa Time on the previous day.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app, has_app_context

DEFAULT_FARM_TIMEZONE = 'Africa/Nairobi'


def farm_timezone() -> ZoneInfo:
    name = current_app.config.get('FARM_TIMEZONE', DEFAULT_FARM_TIMEZONE) if has_app_context() else DEFAULT_FARM_TIMEZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_FARM_TIMEZONE)


def farm_timezone_name() -> str:
    """IANA name of the zone actually in use, e.g. 'Africa/Nairobi'."""
    return farm_timezone().key


def farm_today() -> date:
    return datetime.now(timezone.utc).astimezone(farm_timezone()).date()


def to_farm_date(value: datetime | None) -> date | None:
    """The farm-local calendar date of a stored (UTC) timestamp."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(farm_timezone()).date()


def farm_timestamp_for(local_date: date, now: datetime | None = None) -> datetime:
    """An aware timestamp on ``local_date`` at the farm's current wall-clock time.

    Used when a user picks a calendar date for a record: combining the picked date
    with the UTC time of day would move entries made between 00:00 and 03:00 EAT
    onto the following local day.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    zone = farm_timezone()
    local_time = now.astimezone(zone).timetz().replace(tzinfo=None)
    return datetime.combine(local_date, local_time, tzinfo=zone).astimezone(timezone.utc)


def local_date_sql(column):
    """SQL expression for the farm-local date of a ``timestamptz`` column.

    ``timezone(text, timestamptz)`` is IMMUTABLE in PostgreSQL, so this exact
    expression is also usable in an index (see the period-totals migration).
    """
    from sqlalchemy import Date, cast, func, literal_column

    # Inlined as a constant (not a bind parameter) so the planner can match the
    # expression index. The name is a validated IANA key from ZoneInfo.
    zone_name = farm_timezone_name().replace("'", "''")
    return cast(func.timezone(literal_column(f"'{zone_name}'"), column), Date)

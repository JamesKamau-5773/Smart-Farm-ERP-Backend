"""``period`` / ``anchor`` / ``levels`` query parameters for the period-totals endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.period_resolver import LEVEL_ORDER, Level, Period
from app.utils.api_errors import ApiError


def _unprocessable(code: str, message: str) -> ApiError:
    return ApiError(code, message, status=422)


@dataclass(frozen=True)
class PeriodQuery:
    period: Period
    anchor: date

    @classmethod
    def from_args(cls, args, *, today: date) -> 'PeriodQuery':
        raw_period = str(args.get('period') or Period.MONTH.value).strip().lower()
        try:
            period = Period(raw_period)
        except ValueError:
            raise _unprocessable('INVALID_PERIOD', 'period must be one of week, month or year.') from None

        raw_anchor = args.get('anchor')
        if raw_anchor in (None, ''):
            return cls(period=period, anchor=today)
        try:
            anchor = date.fromisoformat(str(raw_anchor).strip())
        except ValueError:
            raise _unprocessable('INVALID_ANCHOR', 'anchor must be a valid date in YYYY-MM-DD format.') from None
        if len(str(raw_anchor).strip()) != 10:
            raise _unprocessable('INVALID_ANCHOR', 'anchor must be a valid date in YYYY-MM-DD format.')
        return cls(period=period, anchor=anchor)


@dataclass(frozen=True)
class GroupLevelsQuery:
    levels: tuple[Level, ...]

    @classmethod
    def from_args(cls, args) -> 'GroupLevelsQuery':
        raw = str(args.get('levels') or ','.join(level.value for level in LEVEL_ORDER))
        requested = set()
        for part in raw.split(','):
            part = part.strip().lower()
            if not part:
                continue
            try:
                requested.add(Level(part))
            except ValueError:
                raise _unprocessable('INVALID_LEVELS', 'levels must be a comma-separated list of year, month, week, day.') from None
        if not requested:
            raise _unprocessable('INVALID_LEVELS', 'levels must name at least one of year, month, week, day.')
        return cls(levels=tuple(level for level in LEVEL_ORDER if level in requested))

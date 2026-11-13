"""Timezone-aware date-time helpers for values stored or received as ISO 8601."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Treats a naive value (as SQLite returns them) as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def parse_iso_datetime(value) -> Optional[datetime]:
    """None for an empty value; raises ValueError for one that isn't ISO 8601."""
    if value in (None, ''):
        return None
    return as_utc(datetime.fromisoformat(str(value).replace('Z', '+00:00')))

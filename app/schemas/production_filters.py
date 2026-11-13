"""Milk production list filters, shared by ``GET /production/yield`` and the production totals."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models.supply import MilkLog
from app.schemas.ledger_filters import _invalid, _parse_date
from app.utils.api_errors import ApiError


@dataclass(frozen=True)
class ProductionFilters:
    anomaly_only: bool = False
    # One of MilkLog.STATUSES, matched against the status each row is reported with.
    status: str | None = None
    session: str | None = None
    search: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    @property
    def narrows_to_milkings(self) -> bool:
        """True when a filter selects particular milkings, which calf feedings can't be matched to."""
        return self.anomaly_only or bool(self.status) or bool(self.session) or bool(self.search)

    @classmethod
    def from_args(cls, args) -> 'ProductionFilters':
        raw_status = str(args.get('status') or '').strip()
        status = None
        anomaly_only = False
        if raw_status.lower() == 'anomaly':
            # Older clients: anything the anomaly check flagged, whatever its status now.
            anomaly_only = True
        elif raw_status:
            status = raw_status.upper()
            if status not in MilkLog.STATUSES:
                raise ApiError(
                    'VALIDATION_ERROR',
                    f"status must be one of {', '.join(MilkLog.STATUSES)}.",
                    status=400,
                    fields={'status': 'invalid'},
                )
        date_from = _parse_date(args, 'date_from', 'start_date')
        date_to = _parse_date(args, 'date_to', 'end_date')
        if date_from and date_to and date_to < date_from:
            raise _invalid('date_to cannot be earlier than date_from.')
        return cls(
            anomaly_only=anomaly_only,
            status=status,
            session=str(args.get('session') or '').strip() or None,
            search=str(args.get('search') or '').strip() or None,
            date_from=date_from,
            date_to=date_to,
        )

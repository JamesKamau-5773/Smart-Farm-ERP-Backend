"""The one filter builder for milk production queries (list and totals)."""
from __future__ import annotations

from sqlalchemy import case, func, or_, select

from app.models.livestock import Cow
from app.models.supply import MilkLog
from app.schemas.production_filters import ProductionFilters
from app.services.period_resolver import DateRange
from app.services.request_scope import FarmScope
from app.utils.farm_time import local_date_sql


def milk_local_date():
    """Farm-local calendar date of a milking (matches ix_milk_logs_tenant_local_date)."""
    return local_date_sql(MilkLog.timestamp)


def milk_status_sql():
    """The status a milking is reported with, in SQL.

    Mirrors ``_milk_log_status`` in app.api.operations, so filtering and counting by status
    agree with the ``status`` each row carries: verified wins, then the anomaly flag, then
    isolation (not saleable); everything else is RECORDED.
    """
    return case(
        (or_(func.upper(MilkLog.status) == MilkLog.STATUS_VERIFIED, MilkLog.verified_at.isnot(None)),
         MilkLog.STATUS_VERIFIED),
        (MilkLog.anomaly_flag.is_(True), MilkLog.STATUS_FLAGGED),
        (MilkLog.is_saleable.is_(False), MilkLog.STATUS_ISOLATED),
        else_=MilkLog.STATUS_RECORDED,
    )


def apply_production_filters(query, scope: FarmScope, filters: ProductionFilters,
                             date_range: DateRange | None = None):
    # milk_logs carries no farm_id: production is scoped by the JWT's tenant.
    query = query.filter(MilkLog.tenant_id == scope.tenant_id)

    local_date = milk_local_date()
    if filters.date_from is not None:
        query = query.filter(local_date >= filters.date_from)
    if filters.date_to is not None:
        query = query.filter(local_date <= filters.date_to)
    if date_range is not None:
        query = query.filter(local_date >= date_range.start, local_date <= date_range.end)

    if filters.anomaly_only:
        query = query.filter(MilkLog.anomaly_flag.is_(True))
    if filters.status:
        query = query.filter(milk_status_sql() == filters.status)
    if filters.session:
        query = query.filter(func.lower(func.trim(MilkLog.session)) == filters.session.lower())
    if filters.search:
        pattern = f'%{filters.search}%'
        matching_cows = select(Cow.id).where(
            Cow.tenant_id == scope.tenant_id,
            or_(Cow.tag_number.ilike(pattern), Cow.name.ilike(pattern)),
        )
        query = query.filter(MilkLog.cow_id.in_(matching_cows))
    return query

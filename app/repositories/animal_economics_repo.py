"""Persistence queries for animal lifecycle economics."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func

from app import db
from app.models.finance import AnimalCostAllocation, Delivery, SalesLedger
from app.models.livestock import Cow, LactationCycle
from app.models.supply import MilkLog


class AnimalEconomicsRepository:
    """Provides tenant-scoped data needed by animal economics calculations."""

    @staticmethod
    def get_cow(*, tenant_id: int, cow_id: int) -> Cow | None:
        return Cow.query.filter_by(id=cow_id, tenant_id=tenant_id).first()

    @staticmethod
    def list_cost_allocations(*, tenant_id: int, cow_id: int) -> list[AnimalCostAllocation]:
        return AnimalCostAllocation.query.filter_by(
            tenant_id=tenant_id,
            cow_id=cow_id,
        ).order_by(AnimalCostAllocation.occurred_on.asc(), AnimalCostAllocation.id.asc()).all()

    @staticmethod
    def get_first_calving_date(*, cow_id: int) -> date | None:
        return db.session.query(func.min(LactationCycle.actual_calving_date)).filter(
            LactationCycle.cow_id == cow_id,
            LactationCycle.actual_calving_date.isnot(None),
        ).scalar()

    @staticmethod
    def get_saleable_milk_by_day(*, tenant_id: int, cow_id: int) -> dict[date, float]:
        rows = db.session.query(
            func.date(MilkLog.timestamp),
            func.coalesce(func.sum(MilkLog.amount_liters), 0),
        ).filter(
            MilkLog.tenant_id == tenant_id,
            MilkLog.cow_id == cow_id,
            MilkLog.is_saleable.is_(True),
        ).group_by(func.date(MilkLog.timestamp)).all()
        return {day: float(liters) for day, liters in rows if day is not None}

    @staticmethod
    def get_herd_saleable_milk_by_day(*, tenant_id: int, days: list[date]) -> dict[date, float]:
        if not days:
            return {}
        rows = db.session.query(
            func.date(MilkLog.timestamp),
            func.coalesce(func.sum(MilkLog.amount_liters), 0),
        ).filter(
            MilkLog.tenant_id == tenant_id,
            MilkLog.is_saleable.is_(True),
            func.date(MilkLog.timestamp).in_(days),
        ).group_by(func.date(MilkLog.timestamp)).all()
        return {day: float(liters) for day, liters in rows if day is not None}

    @staticmethod
    def get_milk_sales_revenue_by_day(*, tenant_id: int, days: list[date]) -> dict[date, float]:
        if not days:
            return {}
        totals = {day: 0.0 for day in days}
        delivery_rows = db.session.query(
            Delivery.date,
            func.coalesce(func.sum(Delivery.total_price), 0),
        ).filter(
            Delivery.tenant_id == tenant_id,
            Delivery.date.in_(days),
        ).group_by(Delivery.date).all()
        sales_rows = db.session.query(
            SalesLedger.date,
            func.coalesce(func.sum(SalesLedger.total_amount), 0),
        ).filter(
            SalesLedger.tenant_id == tenant_id,
            SalesLedger.date.in_(days),
        ).group_by(SalesLedger.date).all()
        for day, amount in [*delivery_rows, *sales_rows]:
            if day is not None:
                totals[day] = totals.get(day, 0.0) + float(amount)
        return totals

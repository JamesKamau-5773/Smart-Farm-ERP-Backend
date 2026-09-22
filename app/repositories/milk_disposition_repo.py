from datetime import datetime, time, timezone
from decimal import Decimal

from sqlalchemy import func

from app import db
from app.models.finance import Delivery, SalesLedger
from app.models.supply import MilkDisposition, MilkLog


class MilkDispositionRepository:
    @staticmethod
    def create(*, tenant_id, disposition_type, disposition_date, liters, calf_id, notes, recorded_by):
        disposition = MilkDisposition(
            tenant_id=tenant_id,
            disposition_type=disposition_type,
            disposition_date=disposition_date,
            liters=liters,
            calf_id=calf_id,
            notes=notes,
            recorded_by=recorded_by,
        )
        db.session.add(disposition)
        db.session.flush()
        return disposition

    @staticmethod
    def list_for_tenant(*, tenant_id, disposition_date=None, calf_id=None):
        query = MilkDisposition.query.filter_by(tenant_id=tenant_id)
        if disposition_date is not None:
            query = query.filter(MilkDisposition.disposition_date == disposition_date)
        if calf_id is not None:
            query = query.filter(MilkDisposition.calf_id == calf_id)
        return query.order_by(MilkDisposition.disposition_date.desc(), MilkDisposition.id.desc()).all()

    @staticmethod
    def lock_saleable_production(*, tenant_id, disposition_date):
        start = datetime.combine(disposition_date, time.min, tzinfo=timezone.utc)
        end = datetime.combine(disposition_date, time.max, tzinfo=timezone.utc)
        logs = MilkLog.query.filter(
            MilkLog.tenant_id == tenant_id,
            MilkLog.timestamp >= start,
            MilkLog.timestamp <= end,
            MilkLog.is_saleable.is_(True),
        ).with_for_update().all()
        return sum((Decimal(str(log.amount_liters)) for log in logs), Decimal('0'))

    @staticmethod
    def inventory_usage(*, tenant_id, disposition_date):
        buyer_sales = db.session.query(func.coalesce(func.sum(SalesLedger.liters_sold), 0)).filter(
            SalesLedger.tenant_id == tenant_id,
            SalesLedger.date == disposition_date,
        ).scalar() or 0
        customer_deliveries = db.session.query(func.coalesce(func.sum(Delivery.liters_delivered), 0)).filter(
            Delivery.tenant_id == tenant_id,
            Delivery.date == disposition_date,
        ).scalar() or 0
        dispositions = db.session.query(func.coalesce(func.sum(MilkDisposition.liters), 0)).filter(
            MilkDisposition.tenant_id == tenant_id,
            MilkDisposition.disposition_date == disposition_date,
        ).scalar() or 0
        return {
            'buyer_sales': Decimal(str(buyer_sales)),
            'customer_deliveries': Decimal(str(customer_deliveries)),
            'dispositions': Decimal(str(dispositions)),
        }


class MilkInventoryRepository:
    @staticmethod
    def summary_for_date(*, tenant_id, inventory_date):
        start = datetime.combine(inventory_date, time.min, tzinfo=timezone.utc)
        end = datetime.combine(inventory_date, time.max, tzinfo=timezone.utc)
        production = db.session.query(
            func.coalesce(func.sum(MilkLog.amount_liters), 0),
            func.coalesce(func.sum(MilkLog.amount_liters).filter(MilkLog.is_saleable.is_(True)), 0),
        ).filter(
            MilkLog.tenant_id == tenant_id,
            MilkLog.timestamp >= start,
            MilkLog.timestamp <= end,
        ).first()
        usage = MilkDispositionRepository.inventory_usage(
            tenant_id=tenant_id,
            disposition_date=inventory_date,
        )
        produced = Decimal(str(production[0] or 0))
        medically_saleable = Decimal(str(production[1] or 0))
        allocated = usage['buyer_sales'] + usage['customer_deliveries'] + usage['dispositions']
        return {
            'produced_liters': produced,
            'medically_saleable_liters': medically_saleable,
            'buyer_sales_liters': usage['buyer_sales'],
            'customer_delivery_liters': usage['customer_deliveries'],
            'disposition_liters': usage['dispositions'],
            'remaining_liters': medically_saleable - allocated,
        }

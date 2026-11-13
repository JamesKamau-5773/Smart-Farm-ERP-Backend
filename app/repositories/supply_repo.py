from __future__ import annotations
from decimal import Decimal
from typing import Optional
from datetime import datetime, timezone, timedelta

from app import db
from app.utils.farm_time import farm_timestamp_for, to_farm_date
from app.models.supply import InventoryItem, InventoryTransaction, MilkLog, MilkDropAlert
from app.services.inventory_costing_service import InventoryCostingService
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError


class InventoryItemInUseError(Exception):
    """Raised when an item cannot be deleted because other records depend on it."""

    def __init__(self, item):
        super().__init__(f'Inventory item {item.id} is in use.')
        self.item = item


class InventoryRepository:
    MODEL = InventoryItem

    @classmethod
    def get_item(cls, item_id: int, tenant_id: int) -> Optional[InventoryItem]:
        return InventoryItem.query.filter_by(id=item_id, tenant_id=tenant_id).first()

    @classmethod
    def get_items_by_ids(cls, tenant_id: int, item_ids: list[int]) -> list[InventoryItem]:
        if not item_ids:
            return []
        return InventoryItem.query.filter(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.id.in_(item_ids),
        ).order_by(InventoryItem.name.asc()).all()

    @classmethod
    def list_by_tenant(cls, tenant_id: int, *, include_archived: bool = False) -> list[InventoryItem]:
        query = InventoryItem.query.filter_by(tenant_id=tenant_id)
        if not include_archived:
            query = query.filter(InventoryItem.is_active.is_(True))
        return query.order_by(InventoryItem.name.asc()).all()

    @classmethod
    def list_stock_snapshot(cls, tenant_id: int) -> list[InventoryItem]:
        return cls.list_by_tenant(tenant_id)

    @classmethod
    def set_item_active(cls, item_id: int, tenant_id: int, is_active: bool) -> Optional[InventoryItem]:
        item = cls.get_item(item_id, tenant_id)
        if item:
            item.is_active = is_active
            db.session.commit()
        return item

    @classmethod
    def list_transactions_by_tenant(cls, tenant_id: int) -> list[InventoryTransaction]:
        return InventoryTransaction.query.filter_by(tenant_id=tenant_id).order_by(InventoryTransaction.transaction_date.desc()).all()

    @classmethod
    def create_item(cls, **kwargs) -> InventoryItem:
        # Check for uniqueness on (tenant_id, name)
        existing = InventoryItem.query.filter_by(
            tenant_id=kwargs.get('tenant_id'),
            name=kwargs.get('name')
        ).first()
        if existing:
            raise ValueError(f"An inventory item with the name '{kwargs.get('name')}' already exists.")

        item = InventoryItem(**kwargs)
        db.session.add(item)
        db.session.commit()
        return item

    @classmethod
    def update_item(cls, item_id: int, tenant_id: int, **kwargs) -> Optional[InventoryItem]:
        item = cls.get_item(item_id, tenant_id)
        if not item:
            return None

        for key, value in kwargs.items():
            if value is not None:
                setattr(item, key, value)

        db.session.commit()
        return item

    @classmethod
    def delete_item(cls, item_id: int, tenant_id: int) -> Optional[InventoryItem]:
        item = cls.get_item(item_id, tenant_id)
        if item:
            db.session.delete(item)
            try:
                db.session.commit()
            except IntegrityError as error:
                # Recipes, batches and stock history reference the item (FK RESTRICT).
                db.session.rollback()
                raise InventoryItemInUseError(item) from error
        return item

    @classmethod
    def deduct_stock(cls, item_id: int, amount: float, user_id: int, notes: str, tenant_id: int):
        item, transaction, is_low_stock = cls.record_transaction(
            item_id=item_id,
            transaction_type='OUT',
            quantity=amount,
            logged_by=user_id,
            notes=notes,
            tenant_id=tenant_id,
            reason_code='CONSUMPTION'
        )
        return item, is_low_stock

    @classmethod
    def record_transaction(
        cls,
        item_id: int,
        transaction_type: str,
        quantity: float,
        tenant_id: int,
        *,
        reason_code: str = 'STANDARD',
        unit_cost: Optional[float] = None,
        inventory_batch_id: Optional[int] = None,
        logged_by: Optional[int] = None,
        notes: Optional[str] = None,
        commit: bool = True,
    ):
        item = cls.get_item(item_id, tenant_id)
        if not item:
            raise ValueError(f"Inventory item {item_id} not found for tenant {tenant_id}.")

        qty_decimal = Decimal(str(quantity))
        if qty_decimal <= 0:
            raise ValueError("Transaction quantity must be greater than zero.")
        delivered_unit_cost = None
        if unit_cost not in (None, ''):
            delivered_unit_cost = Decimal(str(unit_cost))
            if delivered_unit_cost < 0:
                raise ValueError("unit_cost cannot be negative.")

        if transaction_type == 'OUT':
            if item.current_qty < qty_decimal:
                raise ValueError(f"Insufficient stock for {item.name}. Required: {qty_decimal}, Available: {item.current_qty}.")
            item.current_qty -= qty_decimal
        elif transaction_type == 'IN':
            if delivered_unit_cost is not None:
                item.cost_per_kg = InventoryCostingService.weighted_average_cost(
                    on_hand_qty=item.current_qty,
                    current_unit_cost=item.cost_per_kg,
                    received_qty=qty_decimal,
                    received_unit_cost=delivered_unit_cost,
                )
            item.current_qty += qty_decimal
        else:
            raise ValueError("Invalid transaction_type. Must be 'IN' or 'OUT'.")

        resolved_unit_cost = delivered_unit_cost if delivered_unit_cost is not None else item.cost_per_kg

        # `tenant_id` isn't a column on InventoryTransaction (tenant scoping
        # comes through the linked item); `total_transaction_value` is a
        # Postgres GENERATED ALWAYS column and can't be set explicitly.
        transaction = InventoryTransaction(
            item_id=item_id,
            transaction_type=transaction_type,
            quantity=qty_decimal,
            unit_cost=resolved_unit_cost,
            inventory_batch_id=inventory_batch_id,
            logged_by=logged_by,
            notes=notes,
            reason_code=reason_code,
            transaction_date=datetime.now(timezone.utc)
        )
        db.session.add(transaction)
        if commit:
            db.session.commit()
        else:
            # The caller completes a larger unit of work (e.g. receiving + ledger posting).
            db.session.flush()

        is_low_stock = item.current_qty <= item.minimum_threshold
        return item, transaction, is_low_stock


class MilkRepository:
    @staticmethod
    def get_cow_average_yield(cow_id: int, days: int, tenant_id: int, as_of=None) -> float:
        """Calculates the average yield per session for a cow over the N days prior to as_of (default: now)."""
        if days <= 0:
            return 0.0

        reference = as_of or datetime.now(timezone.utc)
        start_date = reference - timedelta(days=days)

        avg_yield = db.session.query(func.avg(MilkLog.amount_liters)).filter(
            MilkLog.cow_id == cow_id,
            MilkLog.tenant_id == tenant_id,
            MilkLog.timestamp >= start_date,
            MilkLog.timestamp < reference
        ).scalar()

        return float(avg_yield or 0.0)

    @staticmethod
    def create_log(
        cow_id: int,
        amount: float,
        session: str,
        recorded_by: int,
        tenant_id: int,
        is_saleable: bool,
        is_anomaly: bool,
        milking_date=None
    ) -> MilkLog:
        """Creates a new milk log entry and sets its initial status."""
        now = datetime.now(timezone.utc)
        # Preserve the farm's current time-of-day but honor an explicitly submitted milking date.
        timestamp = farm_timestamp_for(milking_date, now) if milking_date else now
        log = MilkLog(
            cow_id=cow_id, amount_liters=Decimal(str(amount)), session=session,
            recorded_by=recorded_by, tenant_id=tenant_id, is_saleable=is_saleable,
            anomaly_flag=is_anomaly, timestamp=timestamp
        )

        log.status = MilkLog.STATUS_FLAGGED if is_anomaly else \
                     MilkLog.STATUS_ISOLATED if not is_saleable else \
                     MilkLog.STATUS_RECORDED
        db.session.add(log)
        db.session.commit()
        return log

    @staticmethod
    def create_drop_alert(cow_id: int, tenant_id: int, alert_date, missing_milk_liters: float, reason: str) -> MilkDropAlert:
        """Raises a manager-review alert for a detected milk-yield drop."""
        alert = MilkDropAlert(
            cow_id=cow_id, tenant_id=tenant_id, alert_date=alert_date,
            missing_milk_liters=Decimal(str(missing_milk_liters)), reason=reason
        )
        db.session.add(alert)
        db.session.commit()
        return alert
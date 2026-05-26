from decimal import Decimal

from app.models.supply import InventoryItem, MilkLog, InventoryTransaction
from app import db
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

class MilkRepository:
    @staticmethod
    def create_log(cow_id: int, amount: float, session: str, recorded_by: int, is_saleable: bool, is_anomaly: bool, butterfat_pct=None) -> MilkLog:
        """Logs a milking session."""
        try:
            log = MilkLog(
                cow_id=cow_id,
                amount_liters=amount,
                session=session,
                recorded_by=recorded_by,
                butterfat_pct=butterfat_pct,
                is_saleable=is_saleable,
                anomaly_flag=is_anomaly
            )
            db.session.add(log)
            db.session.commit()
            return log
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Failed, Database error while saving milk log.")

    @staticmethod
    def get_cow_average_yield(cow_id: int, days: int = 7) -> float:
        """Calculates the average yield for a specific cow over a rolling window."""
        start_date = datetime.utcnow() - timedelta(days=days)
        result = db.session.query(func.avg(MilkLog.amount_liters)).filter(
            MilkLog.cow_id == cow_id,
            MilkLog.timestamp >= start_date
        ).scalar()
        
        # If no previous records exist, return the average as 0
        return float(result) if result else 0.0

    @staticmethod
    def get_cow_average_butterfat(cow_id: int, days: int = 30) -> float:
        """Calculates the average butterfat percentage for a specific cow over a rolling window."""
        start_date = datetime.utcnow() - timedelta(days=days)
        result = db.session.query(func.avg(MilkLog.butterfat_pct)).filter(
            MilkLog.cow_id == cow_id,
            MilkLog.timestamp >= start_date,
            MilkLog.butterfat_pct.isnot(None),
        ).scalar()

        return float(result) if result is not None else 0.0

class InventoryRepository:
    @staticmethod
    def get_item(item_id: str, tenant_id: int = None) -> InventoryItem:
        item = db.session.get(InventoryItem, item_id)
        if item and tenant_id is not None and item.tenant_id != tenant_id:
            return None
        return item

    @staticmethod
    def list_by_tenant(tenant_id: int) -> list[InventoryItem]:
        return InventoryItem.query.filter_by(tenant_id=tenant_id).order_by(InventoryItem.name.asc()).all()

    @staticmethod
    def create_item(
        *,
        tenant_id: int,
        name: str,
        category: str,
        unit: str,
        current_qty=0,
        minimum_threshold=0,
    ) -> InventoryItem:
        try:
            item = InventoryItem(
                tenant_id=tenant_id,
                name=name,
                category=category,
                unit=unit,
                current_qty=current_qty,
                minimum_threshold=minimum_threshold,
            )
            db.session.add(item)
            db.session.commit()
            return item
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception("Failed, Database error while saving inventory item.")

    @staticmethod
    def record_transaction(
        *,
        item_id: str,
        transaction_type: str,
        quantity,
        logged_by: int = None,
        reference_note: str = None,
        tenant_id: int = None,
    ) -> tuple[InventoryItem, InventoryTransaction, bool]:
        try:
            item = InventoryRepository.get_item(item_id, tenant_id=tenant_id)
            if not item:
                raise ValueError("Inventory item not found.")

            quantity_value = Decimal(str(quantity))
            transaction_type = (transaction_type or "").strip().upper()
            if transaction_type not in {"IN", "OUT"}:
                raise ValueError("transaction_type must be IN or OUT.")

            if transaction_type == "OUT":
                if item.current_qty < quantity_value:
                    raise ValueError(f"Insufficient stock for {item.name}. Available: {item.current_qty} {item.unit}")
                item.current_qty -= quantity_value
            else:
                item.current_qty = (item.current_qty or Decimal("0")) + quantity_value

            transaction = InventoryTransaction(
                item_id=item.id,
                transaction_type=transaction_type,
                quantity=quantity_value,
                reference_note=reference_note,
                logged_by=logged_by,
            )
            db.session.add(transaction)
            db.session.commit()

            is_low_stock = item.current_qty <= item.minimum_threshold
            return item, transaction, is_low_stock
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception("Database error while recording inventory transaction.")

    @staticmethod
    def get_by_id(item_id: str, tenant_id: int = None) -> InventoryItem:
        return InventoryRepository.get_item(item_id, tenant_id=tenant_id)

    @staticmethod
    def deduct_stock(item_id: str, amount: float, user_id: int, target_cow: int = None, notes: str = None, tenant_id: int = None):
        """Compatibility wrapper for stock deductions recorded in the new ledger."""
        reference_note = notes
        if target_cow is not None:
            target_suffix = f"Target cow ID: {target_cow}."
            reference_note = f"{notes}. {target_suffix}" if notes else target_suffix

        item, _, is_low_stock = InventoryRepository.record_transaction(
            item_id=item_id,
            transaction_type="OUT",
            quantity=amount,
            logged_by=user_id,
            reference_note=reference_note,
            tenant_id=tenant_id,
        )
        return item, is_low_stock

    @staticmethod
    def add_stock(item_id: str, amount: float, user_id: int = None, notes: str = None, tenant_id: int = None):
        item, _, is_low_stock = InventoryRepository.record_transaction(
            item_id=item_id,
            transaction_type="IN",
            quantity=amount,
            logged_by=user_id,
            reference_note=notes,
            tenant_id=tenant_id,
        )
        return item, is_low_stock
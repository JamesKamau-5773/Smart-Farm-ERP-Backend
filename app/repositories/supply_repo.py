from app.models.supply import StoreItem, MilkLog, FeedRequisition
from app import db
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

class MilkRepository:
    @staticmethod
    def create_log(cow_id: int, amount: float, session: str, recorded_by: int, is_saleable: bool, is_anomaly: bool) -> MilkLog:
        """Logs a milking session."""
        try:
            log = MilkLog(
                cow_id=cow_id,
                amount_liters=amount,
                session=session,
                recorded_by=recorded_by,
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

class InventoryRepository:
    @staticmethod
    def get_item(item_id: int) -> StoreItem:
        return StoreItem.query.get(item_id)

    @staticmethod
    def deduct_stock(item_id: int, amount: float, user_id: int, target_cow: int = None, notes: str = None):
        """Deducts inventory and creates a permanent Requisition Audit log."""
        try:
            item = StoreItem.query.get(item_id)
            if not item:
                raise ValueError("Item not found in store.")
            
            if item.current_stock < amount:
                raise ValueError(f"Insufficient stock for {item.name}. Available: {item.current_stock} {item.unit_of_measure}")

            # 1. Deduct Stock
            item.current_stock -= amount
            
            # 2. Create Audit Trail
            req = FeedRequisition(
                item_id=item_id,
                amount_used=amount,
                recorded_by=user_id,
                target_cow_id=target_cow,
                notes=notes
            )
            db.session.add(req)
            db.session.commit()
            
            # Return True if stock hit minimum threshold
            is_low_stock = item.current_stock <= item.min_threshold
            return item, is_low_stock
            
        except SQLAlchemyError as e:
            db.session.rollback()
            raise Exception("Database error while deducting inventory.")
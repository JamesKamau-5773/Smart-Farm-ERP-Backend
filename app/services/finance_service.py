from app import db
from app.models.finance import Transaction, TransactionType, TransactionCategory
from app.models.supply import MilkLog
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import jsonify
from .audit_service import record_audit

class FinanceService:
    @staticmethod
    def calculate_daily_unit_cost(target_date: datetime.date = None):
        """
        Calculates the real cost of production per liter for a specific day.
        """
        if target_date is None:
            target_date = datetime.utcnow().date()
            
        start_of_day = datetime.combine(target_date, datetime.min.time())
        end_of_day = start_of_day + timedelta(days=1)

        # 1. Calculate Total Saleable Volume (The Denominator)
        saleable_volume = db.session.query(func.sum(MilkLog.amount_liters)).filter(
            MilkLog.timestamp >= start_of_day,
            MilkLog.timestamp < end_of_day,
            MilkLog.is_saleable == True
        ).scalar() or 0.0

        if float(saleable_volume) == 0.0:
            return jsonify({
                "date": str(target_date),
                "error": "No saleable milk recorded for this date. Cannot calculate unit cost."
            }), 400

        # 2. Calculate Total Daily Expenses (The Numerator)
        daily_expenses = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.timestamp >= start_of_day,
            Transaction.timestamp < end_of_day,
            Transaction.transaction_type == TransactionType.EXPENSE
        ).scalar() or 0.0

        # 3. Calculate Unit Cost
        unit_cost = float(daily_expenses) / float(saleable_volume)

        return jsonify({
            "date": str(target_date),
            "total_expenses_kes": float(daily_expenses),
            "total_saleable_liters": float(saleable_volume),
            "unit_cost_per_liter_kes": round(unit_cost, 2)
        }), 200

    @staticmethod
    def record_transaction(t_type: TransactionType, category: TransactionCategory, amount: float, user_id: int, ip_address: str, customer_id: int = None, ref_code: str = None, desc: str = None):
        """Standardized method for recording ledger entries with audit logging."""
        try:
            tx = Transaction(
                transaction_type=t_type,
                category=category,
                amount=amount,
                recorded_by=user_id,
                customer_id=customer_id,
                reference_code=ref_code,
                description=desc
            )
            db.session.add(tx)
            db.session.flush()  # Flush to get the transaction ID

            record_audit(
                user_id=user_id,
                action='RECORD_TRANSACTION',
                entity_type='Transaction',
                entity_id=tx.id,
                old_value=None,
                new_value=f"Type: {t_type.value}, Category: {category.value}, Amount: {amount}",
                ip_address=ip_address
            )

            db.session.commit()
            return tx
        except Exception as e:
            db.session.rollback()
            print(f"Error in record_transaction: {e}")
            return None

                description=desc
            )
            db.session.add(tx)
            db.session.commit()
            return tx
        except Exception as e:
            db.session.rollback()
            raise Exception("Failed to record transaction.")
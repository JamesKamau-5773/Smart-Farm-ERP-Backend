from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import func

from app import db
from app.models.finance import Transaction, TransactionType


class FinanceService:
    """
    A service layer for handling core financial calculations and operations.
    This acts as a single source of truth for financial logic.
    """

    @staticmethod
    def get_daily_financial_summary(tenant_id: int, for_date=None) -> dict:
        """
        Calculates the financial summary for a given day.

        This is the authoritative source for dashboard financial metrics.
        """
        if for_date is None:
            for_date = datetime.now(timezone.utc).date()

        start_of_day = datetime.combine(for_date, datetime.min.time(), tzinfo=timezone.utc)
        end_of_day = datetime.combine(for_date, datetime.max.time(), tzinfo=timezone.utc)

        # Base query for the specified day's transactions
        base_query = db.session.query(
            func.sum(Transaction.amount)
        ).filter(
            Transaction.tenant_id == tenant_id,
            Transaction.timestamp >= start_of_day,
            Transaction.timestamp <= end_of_day
        )

        # FIX: Use the TransactionType.REVENUE enum member instead of a hardcoded string.
        revenue_total = base_query.filter(
            Transaction.transaction_type == TransactionType.REVENUE
        ).scalar() or Decimal('0.0')

        # FIX: Use the TransactionType.EXPENSE enum member for costs.
        feed_cost_total = base_query.filter(
            Transaction.transaction_type == TransactionType.EXPENSE
        ).scalar() or Decimal('0.0')

        net_margin = revenue_total - feed_cost_total

        return {
            'revenue_total_kes': revenue_total,
            'feed_cost_total_kes': feed_cost_total,
            'net_margin_kes': net_margin,
        }
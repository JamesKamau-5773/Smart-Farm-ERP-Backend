from __future__ import annotations
from decimal import Decimal

from app import db
from app.models.finance import Transaction, TransactionCategory
from app.services import ledger_classification
from app.services.ledger_classification import LedgerBucket
from app.utils.farm_time import farm_today, local_date_sql


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
            for_date = farm_today()

        # Same rules as the ledger KPI cards and period totals (LedgerClassification),
        # on the farm-local day rather than the UTC day.
        def day_query(*columns):
            return db.session.query(*columns).filter(
                Transaction.tenant_id == tenant_id,
                local_date_sql(Transaction.timestamp) == for_date,
            )

        revenue_total, total_costs = day_query(
            ledger_classification.bucket_sum(LedgerBucket.INCOME),
            ledger_classification.bucket_sum(LedgerBucket.EXPENSE),
        ).one()
        feed_cost_total = day_query(ledger_classification.bucket_sum(LedgerBucket.EXPENSE)).filter(
            Transaction.category == TransactionCategory.FEED_PURCHASE,
        ).scalar()
        revenue_total = Decimal(str(revenue_total or 0))
        total_costs = Decimal(str(total_costs or 0))
        feed_cost_total = Decimal(str(feed_cost_total or 0))

        net_margin = revenue_total - total_costs

        return {
            'revenue_total_kes': revenue_total,
            'feed_cost_total_kes': feed_cost_total,
            'total_costs_kes': total_costs,
            'net_margin_kes': net_margin,
        }

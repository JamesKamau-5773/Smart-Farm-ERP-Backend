from decimal import Decimal

from app import db
from app.models.finance import CostClass, Transaction, TransactionCategory, TransactionStatus, TransactionType


class PayrollLedgerService:
    @staticmethod
    def reference_code(payroll_run):
        return f'PAYROLL-{payroll_run.payroll_year:04d}-{payroll_run.payroll_month:02d}'

    @staticmethod
    def post_expense(payroll_run, *, actor_id=None):
        reference_code = PayrollLedgerService.reference_code(payroll_run)
        existing = Transaction.query.filter_by(
            tenant_id=payroll_run.tenant_id,
            reference_code=reference_code,
        ).first()
        if existing:
            return existing

        amount = Decimal(str(payroll_run.total_net_pay or 0))
        if amount <= 0:
            return None

        actor_id = int(actor_id) if actor_id is not None else None
        transaction = Transaction(
            tenant_id=payroll_run.tenant_id,
            farm_id=payroll_run.farm_id,
            transaction_type=TransactionType.EXPENSE,
            category=TransactionCategory.LABOR_WAGES,
            amount=amount,
            item_name='Monthly payroll',
            cost_class=CostClass.COGS,
            description=f'Payroll for {payroll_run.payroll_year:04d}-{payroll_run.payroll_month:02d}',
            counterparty_name='Employees',
            reference_code=reference_code,
            timestamp=payroll_run.finalized_at,
            recorded_by=actor_id,
            status=TransactionStatus.POSTED.value,
            posted_at=payroll_run.finalized_at,
            posted_by=actor_id,
        )
        db.session.add(transaction)
        db.session.flush()
        return transaction

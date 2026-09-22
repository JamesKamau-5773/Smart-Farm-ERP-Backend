from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app import db
from app.models.finance import Customer, Transaction, TransactionCategory, TransactionType
from app.models.finance import TransactionStatus
from app.services.receipt_service import ReceiptService


class PaymentService:
    """Owns payment validation, receipt creation, and customer balance updates."""

    @staticmethod
    def create_payment_transaction(
        *,
        tenant_id: int,
        amount,
        category: TransactionCategory,
        customer_id: int | None = None,
        buyer_id: int | None = None,
        reference_code: str | None = None,
        recorded_by: int | None = None,
        description: str | None = None,
        payment_method: str | None = None,
        timestamp: datetime | None = None,
    ) -> Transaction:
        try:
            payment_amount = Decimal(str(amount))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError('amount must be a valid number') from exc

        reference_code = str(reference_code or '').strip() or None
        if payment_amount <= 0:
            raise ValueError('amount must be greater than 0')
        if (customer_id is None) == (buyer_id is None):
            raise ValueError('payment must identify exactly one customer or buyer')
        if category not in (TransactionCategory.PAYMENT, TransactionCategory.BUYER_PAYMENT):
            raise ValueError('invalid payment category')
        if reference_code and Transaction.query.filter_by(
            tenant_id=tenant_id,
            reference_code=reference_code,
        ).first():
            raise ValueError('reference_code has already been recorded')

        posted_at = datetime.now(timezone.utc)
        transaction = Transaction(
            tenant_id=tenant_id,
            customer_id=customer_id,
            buyer_id=buyer_id,
            transaction_type=TransactionType.PAYMENT,
            category=category,
            amount=payment_amount,
            description=description,
            payment_method=str(payment_method or '').strip()[:30] or None,
            reference_code=reference_code,
            timestamp=timestamp or posted_at,
            recorded_by=recorded_by,
            status=TransactionStatus.POSTED.value,
            posted_at=posted_at,
            posted_by=recorded_by,
        )
        db.session.add(transaction)
        return transaction

    @staticmethod
    def record_customer_payment(
        *,
        tenant_id: int,
        customer_id: int,
        amount,
        reference_code: str,
        recorded_by: int | None = None,
        description: str | None = None,
        payment_method: str | None = None,
        timestamp: datetime | None = None,
    ) -> tuple[Customer, Transaction]:
        reference_code = str(reference_code or '').strip()
        if not reference_code:
            raise ValueError('reference_code is required')

        customer = Customer.query.filter_by(
            id=customer_id,
            tenant_id=tenant_id,
        ).with_for_update().first()
        if not customer:
            raise ValueError('Customer not found for this tenant')

        transaction = PaymentService.create_payment_transaction(
            tenant_id=tenant_id,
            customer_id=customer.id,
            amount=amount,
            category=TransactionCategory.PAYMENT,
            reference_code=reference_code,
            recorded_by=recorded_by,
            description=description or f'Payment from {customer.name}',
            payment_method=payment_method,
            timestamp=timestamp,
        )
        db.session.flush()
        ReceiptService.issue(transaction, issued_by=recorded_by)
        customer.account_balance = Decimal(customer.account_balance or 0) - transaction.amount
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return customer, transaction

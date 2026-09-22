"""Auditable corrections for historical ledger classification errors."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app import db
from app.models.finance import (
    CostClass,
    Customer,
    Transaction,
    TransactionAuditLog,
    TransactionCategory,
    TransactionStatus,
    TransactionType,
)
from app.services.payment_service import PaymentService
from app.services.receipt_service import ReceiptService


class LedgerCorrectionService:
    """Reclassifies erroneous customer revenue as payment without deleting history."""

    _EXPENSE_CATEGORIES = {
        TransactionCategory.FEED_PURCHASE,
        TransactionCategory.VET_FEES,
        TransactionCategory.LABOR_WAGES,
        TransactionCategory.UTILITIES,
        TransactionCategory.EQUIPMENT_MAINTENANCE,
        TransactionCategory.TRANSPORT,
        TransactionCategory.OPENING_BALANCE,
        TransactionCategory.INVENTORY_WRITE_OFF,
        TransactionCategory.OTHER,
    }
    _DEFAULT_COST_CLASS_BY_CATEGORY = {
        TransactionCategory.FEED_PURCHASE: CostClass.COGS,
        TransactionCategory.VET_FEES: CostClass.COGS,
        TransactionCategory.LABOR_WAGES: CostClass.COGS,
        TransactionCategory.UTILITIES: CostClass.COGS,
        TransactionCategory.INVENTORY_WRITE_OFF: CostClass.COGS,
        TransactionCategory.EQUIPMENT_MAINTENANCE: CostClass.OPERATING,
        TransactionCategory.TRANSPORT: CostClass.OPERATING,
        TransactionCategory.OPENING_BALANCE: CostClass.OPERATING,
        TransactionCategory.OTHER: CostClass.OPERATING,
    }

    @classmethod
    def void_and_replace_expense(
        cls,
        *,
        tenant_id: int,
        transaction_id: int,
        void_reason: str,
        corrected_by: int | None,
        category: str | None = None,
        cost_class: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[Transaction, Transaction]:
        """Voids one posted expense and creates its linked classification replacement."""
        reason = str(void_reason or '').strip()
        if not reason:
            raise ValueError('void_reason is required.')

        original = Transaction.query.filter_by(
            id=transaction_id,
            tenant_id=tenant_id,
        ).with_for_update().first()
        if original is None:
            raise ValueError('Transaction not found.')
        if original.transaction_type != TransactionType.EXPENSE:
            raise ValueError('Only expense transactions can be corrected by this workflow.')
        if original.status != TransactionStatus.POSTED.value:
            raise ValueError('Only posted transactions can be voided and replaced.')
        if original.correction_replacement is not None:
            raise ValueError('This transaction has already been corrected.')

        try:
            replacement_category = TransactionCategory(category) if category else original.category
        except ValueError as exc:
            raise ValueError('Invalid replacement category.') from exc
        if replacement_category not in cls._EXPENSE_CATEGORIES:
            raise ValueError('Replacement category must be valid for an expense transaction.')
        try:
            replacement_cost_class = CostClass(cost_class) if cost_class else cls._DEFAULT_COST_CLASS_BY_CATEGORY[replacement_category]
        except ValueError as exc:
            raise ValueError('Invalid replacement cost_class.') from exc

        now = datetime.now(timezone.utc)
        original.status = TransactionStatus.VOIDED.value
        original.voided_at = now
        original.voided_by = corrected_by
        original.void_reason = reason[:255]
        replacement = Transaction(
            tenant_id=original.tenant_id,
            farm_id=original.farm_id,
            transaction_type=TransactionType.EXPENSE,
            category=replacement_category,
            amount=original.amount,
            item_name=original.item_name,
            quantity=original.quantity,
            cost_class=replacement_cost_class,
            description=original.description,
            counterparty_name=original.counterparty_name,
            payment_method=original.payment_method,
            timestamp=original.timestamp,
            recorded_by=corrected_by,
            status=TransactionStatus.POSTED.value,
            posted_at=now,
            posted_by=corrected_by,
            corrected_from_transaction_id=original.id,
        )
        db.session.add(replacement)
        db.session.flush()
        db.session.add(TransactionAuditLog(
            tenant_id=tenant_id,
            transaction_id=original.id,
            action='VOIDED_AND_REPLACED',
            performed_by=corrected_by,
            ip_address=ip_address,
            details={
                'reason': original.void_reason,
                'replacement_transaction_id': replacement.id,
                'previous_category': original.category.value,
                'replacement_category': replacement.category.value,
                'previous_cost_class': original.cost_class.value if original.cost_class else None,
                'replacement_cost_class': replacement.cost_class.value,
            },
        ))
        db.session.add(TransactionAuditLog(
            tenant_id=tenant_id,
            transaction_id=replacement.id,
            action='CREATED_AS_CORRECTION',
            performed_by=corrected_by,
            ip_address=ip_address,
            details={'corrected_from_transaction_id': original.id},
        ))
        return original, replacement

    @staticmethod
    def reclassify_customer_revenue_as_payment(
        *,
        tenant_id: int,
        transaction_id: int,
        payment_reference: str,
        corrected_by: int | None = None,
    ) -> Transaction:
        original = Transaction.query.filter_by(
            id=transaction_id,
            tenant_id=tenant_id,
        ).with_for_update().first()
        if original is None:
            raise ValueError('Transaction not found.')
        if original.transaction_type != TransactionType.REVENUE or original.customer_id is None or original.buyer_id is not None:
            raise ValueError('Only customer-linked revenue transactions can be reclassified as customer payments.')
        if original.status != TransactionStatus.POSTED.value:
            raise ValueError('Only posted transactions can be reclassified.')

        customer = Customer.query.filter_by(
            id=original.customer_id,
            tenant_id=tenant_id,
        ).with_for_update().first()
        if customer is None:
            raise ValueError('Customer not found for this transaction.')

        reference = str(payment_reference or '').strip()
        if not reference:
            raise ValueError('payment_reference is required.')

        try:
            original.status = TransactionStatus.VOIDED.value
            if original.receipt:
                ReceiptService.void(
                    original.receipt,
                    reason=f'Reclassified as customer payment transaction for correction.',
                    voided_by=corrected_by,
                )

            replacement = PaymentService.create_payment_transaction(
                tenant_id=tenant_id,
                customer_id=customer.id,
                amount=original.amount,
                category=TransactionCategory.PAYMENT,
                reference_code=reference,
                recorded_by=corrected_by or original.recorded_by,
                description=f'Correction of ledger transaction #{original.id}: {original.description or "Customer payment"}',
                payment_method=original.payment_method,
                timestamp=original.timestamp,
            )
            db.session.flush()
            ReceiptService.issue(
                replacement,
                issued_by=corrected_by or original.recorded_by,
                farm_id=original.farm_id,
            )
            customer.account_balance = Decimal(customer.account_balance or 0) - replacement.amount
            db.session.commit()
            return replacement
        except Exception:
            db.session.rollback()
            raise

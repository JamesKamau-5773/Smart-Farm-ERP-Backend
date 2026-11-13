"""Auditable corrections to posted ledger entries: the original is voided, never edited or deleted."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app import db
from app.models.finance import (
    Customer,
    Transaction,
    TransactionAuditLog,
    TransactionCategory,
    TransactionStatus,
    TransactionType,
)
from app.repositories.ledger_repo import TransactionAuditLogRepository, TransactionRepository
from app.services.ledger_correction_policy import Correction, LedgerCorrectionPolicy
from app.services.transaction_attachment_service import TransactionAttachmentService
from app.services.payment_service import PaymentService
from app.services.receipt_service import ReceiptService


class LedgerCorrectionService:
    """Corrects posted ledger entries without deleting history: the original is voided and a linked replacement posted."""

    @classmethod
    def void_and_replace_expense(cls, **kwargs) -> tuple[Transaction, Transaction]:
        """Kept for existing callers; corrections now cover income too."""
        return cls.void_and_replace(**kwargs)

    @classmethod
    def void_and_replace(
        cls,
        *,
        tenant_id: int,
        transaction_id: int,
        void_reason: str,
        corrected_by: int | None,
        category: str | None = None,
        cost_class: str | None = None,
        amount=None,
        ip_address: str | None = None,
    ) -> tuple[Transaction, Transaction]:
        """Voids one posted income or expense entry and posts its corrected replacement. The caller commits."""
        original = TransactionRepository.get_for_tenant(transaction_id, tenant_id, for_update=True)
        correction = LedgerCorrectionPolicy.decide(
            original, void_reason=void_reason, category=category, cost_class=cost_class, amount=amount,
        )
        now = datetime.now(timezone.utc)
        original.status = TransactionStatus.VOIDED.value
        original.voided_at = now
        original.voided_by = corrected_by
        original.void_reason = correction.reason
        replacement = TransactionRepository.stage(cls._replacement(original, correction, corrected_by=corrected_by, now=now))
        TransactionAttachmentService.stage_copies(original, replacement)
        if original.transaction_type == TransactionType.REVENUE:
            cls._reissue_receipt(original, replacement, corrected_by=corrected_by, ip_address=ip_address)
        cls._stage_audit(original, replacement, corrected_by=corrected_by, ip_address=ip_address)
        return original, replacement

    @staticmethod
    def _replacement(original: Transaction, correction: Correction, *, corrected_by, now) -> Transaction:
        return Transaction(
            tenant_id=original.tenant_id,
            farm_id=original.farm_id,
            transaction_type=original.transaction_type,
            category=correction.category,
            income_category=original.income_category,
            amount=correction.amount,
            item_name=original.item_name,
            quantity=original.quantity,
            cost_class=correction.cost_class,
            description=original.description,
            counterparty_name=original.counterparty_name,
            payment_method=original.payment_method,
            timestamp=original.timestamp,
            source_document_type=original.source_document_type,
            source_document_id=original.source_document_id,
            recorded_by=corrected_by,
            status=TransactionStatus.POSTED.value,
            posted_at=now,
            posted_by=corrected_by,
            corrected_from_transaction_id=original.id,
        )

    @staticmethod
    def _reissue_receipt(original: Transaction, replacement: Transaction, *, corrected_by, ip_address) -> None:
        """The customer-facing receipt must match the corrected amount."""
        if original.receipt is not None:
            ReceiptService.void(original.receipt, reason=f'Ledger correction: {original.void_reason}',
                                voided_by=corrected_by, ip_address=ip_address)
        ReceiptService.issue(replacement, issued_by=corrected_by, farm_id=original.farm_id, ip_address=ip_address)

    @staticmethod
    def _stage_audit(original: Transaction, replacement: Transaction, *, corrected_by, ip_address) -> None:
        TransactionAuditLogRepository.stage(TransactionAuditLog(
            tenant_id=original.tenant_id,
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
                'replacement_cost_class': replacement.cost_class.value if replacement.cost_class else None,
                'previous_amount': str(original.amount),
                'replacement_amount': str(replacement.amount),
            },
        ))
        TransactionAuditLogRepository.stage(TransactionAuditLog(
            tenant_id=original.tenant_id,
            transaction_id=replacement.id,
            action='CREATED_AS_CORRECTION',
            performed_by=corrected_by,
            ip_address=ip_address,
            details={'corrected_from_transaction_id': original.id},
        ))

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

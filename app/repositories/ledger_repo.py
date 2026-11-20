"""Persistence for ledger entries and their attachments. Callers commit."""
from __future__ import annotations

from app import db
from app.models.finance import Transaction, TransactionAttachment, TransactionAuditLog


class TransactionRepository:
    @staticmethod
    def get_for_tenant(transaction_id: int, tenant_id: int, *, for_update: bool = False) -> Transaction | None:
        query = Transaction.query.filter_by(id=transaction_id, tenant_id=tenant_id)
        if for_update:
            query = query.with_for_update()
        return query.first()

    @staticmethod
    def get_by_reference(tenant_id: int, reference_code: str) -> Transaction | None:
        return Transaction.query.filter_by(tenant_id=tenant_id, reference_code=reference_code).first()

    @staticmethod
    def exists_for_source(tenant_id: int, source_document_type: str, source_document_id: int) -> bool:
        return db.session.query(
            Transaction.query.filter_by(
                tenant_id=tenant_id, source_document_type=source_document_type, source_document_id=source_document_id,
            ).exists()
        ).scalar()

    @staticmethod
    def stage(transaction: Transaction) -> Transaction:
        """Adds the entry and assigns its id."""
        db.session.add(transaction)
        db.session.flush()
        return transaction


class TransactionAttachmentRepository:
    @staticmethod
    def stage(attachment: TransactionAttachment) -> TransactionAttachment:
        db.session.add(attachment)
        return attachment

    @staticmethod
    def get(tenant_id: int, transaction_id: int, attachment_id: int) -> TransactionAttachment | None:
        return TransactionAttachment.query.filter_by(
            id=attachment_id, transaction_id=transaction_id, tenant_id=tenant_id,
        ).first()

    @staticmethod
    def count_for_transaction(transaction_id: int) -> int:
        return TransactionAttachment.query.filter_by(transaction_id=transaction_id).count()


class TransactionAuditLogRepository:
    @staticmethod
    def stage(entry: TransactionAuditLog) -> TransactionAuditLog:
        db.session.add(entry)
        return entry

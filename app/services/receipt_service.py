from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from flask import render_template
from sqlalchemy import text

from app import db
from app.models.farm import Farm
from app.models.finance import (
    Buyer,
    Receipt,
    ReceiptAuditLog,
    ReceiptStatus,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.models.tenant import Tenant
from app.models.user import User
from weasyprint import HTML


class ReceiptService:
    TEMPLATE_VERSION = '2'
    CURRENCY = 'KES'

    @staticmethod
    def is_eligible(transaction: Transaction) -> bool:
        return (
            transaction.status == TransactionStatus.POSTED.value
            and transaction.amount > 0
            and transaction.transaction_type in (TransactionType.PAYMENT, TransactionType.REVENUE)
        )

    @staticmethod
    def _enum_value(value):
        return getattr(value, 'value', value)

    @staticmethod
    def _resolve_farm(transaction: Transaction, farm_id: int | None) -> Farm:
        resolved_id = farm_id or transaction.farm_id
        if resolved_id:
            farm = Farm.query.filter_by(id=resolved_id, tenant_id=transaction.tenant_id).first()
        else:
            farm = Farm.query.filter_by(tenant_id=transaction.tenant_id, is_active=True).order_by(Farm.id).first()
        if not farm:
            raise ValueError('An active farm is required to issue a receipt.')
        return farm

    @staticmethod
    def _next_number(tenant_id: int, fiscal_year: int) -> int:
        return db.session.execute(text("""
            INSERT INTO receipt_number_sequences (tenant_id, fiscal_year, next_number)
            VALUES (:tenant_id, :fiscal_year, 2)
            ON CONFLICT (tenant_id, fiscal_year)
            DO UPDATE SET next_number = receipt_number_sequences.next_number + 1
            RETURNING next_number - 1
        """), {
            'tenant_id': tenant_id,
            'fiscal_year': fiscal_year,
        }).scalar_one()

    @staticmethod
    def _audit(receipt: Receipt, action: str, performed_by: int | None, ip_address: str | None, details=None):
        db.session.add(ReceiptAuditLog(
            tenant_id=receipt.tenant_id,
            receipt_id=receipt.id,
            action=action,
            performed_by=performed_by,
            ip_address=ip_address,
            details=details,
        ))

    @classmethod
    def _render_document(cls, receipt: Receipt) -> bytes:
        return HTML(
            string=render_template('pdf/receipt.html', receipt=cls.serialize(receipt))
        ).write_pdf()

    @classmethod
    def issue(
        cls,
        transaction: Transaction,
        issued_by: int | None = None,
        farm_id: int | None = None,
        ip_address: str | None = None,
    ) -> Receipt:
        if transaction.id is None:
            db.session.flush()

        locked_transaction = Transaction.query.filter_by(id=transaction.id).with_for_update().one()
        if locked_transaction.receipt:
            return locked_transaction.receipt
        if not cls.is_eligible(locked_transaction):
            raise ValueError('Receipts require a positive posted payment or revenue transaction.')

        issued_at = datetime.now(timezone.utc)
        farm = cls._resolve_farm(locked_transaction, farm_id)
        if locked_transaction.farm_id is None:
            locked_transaction.farm_id = farm.id
        tenant = db.session.get(Tenant, locked_transaction.tenant_id)
        issuer = db.session.get(User, issued_by) if issued_by else None
        buyer = db.session.get(Buyer, locked_transaction.buyer_id) if locked_transaction.buyer_id else None
        sequence = cls._next_number(tenant.id, issued_at.year)
        receipt_number = f'RCPT-{issued_at.year}-{sequence:06d}'
        snapshot = {
            'transaction_id': locked_transaction.id,
            'tenant': {
                'id': tenant.id,
                'name': tenant.name,
                'registration_number': tenant.registration_number,
                'region': tenant.region,
            },
            'farm': {'id': farm.id, 'name': farm.name},
            'transaction_date': locked_transaction.timestamp.isoformat() if locked_transaction.timestamp else None,
            'transaction_type': cls._enum_value(locked_transaction.transaction_type),
            'transaction_status': locked_transaction.status,
            'category': cls._enum_value(locked_transaction.category),
            'amount': float(locked_transaction.amount),
            'currency': cls.CURRENCY,
            'counterparty_name': locked_transaction.customer.name if locked_transaction.customer else (
                buyer.name if buyer else locked_transaction.counterparty_name
            ),
            'payment_method': locked_transaction.payment_method,
            'payment_reference': locked_transaction.reference_code,
            'description': locked_transaction.description,
            'issuer': {'id': issuer.id, 'name': issuer.name or issuer.username} if issuer else None,
        }
        receipt = Receipt(
            tenant_id=tenant.id,
            farm_id=farm.id,
            transaction_id=locked_transaction.id,
            receipt_number=receipt_number,
            snapshot=snapshot,
            issued_at=issued_at,
            issued_by=issued_by,
            status=ReceiptStatus.ISSUED.value,
            currency=cls.CURRENCY,
            template_version=cls.TEMPLATE_VERSION,
        )
        document = cls._render_document(receipt)
        receipt.document_content = document
        receipt.document_sha256 = hashlib.sha256(document).hexdigest()
        db.session.add(receipt)
        db.session.flush()
        cls._audit(receipt, 'ISSUED', issued_by, ip_address, {'document_sha256': receipt.document_sha256})
        return receipt

    @classmethod
    def rerender_documents_to_current_template(
        cls,
        *,
        tenant_id: int | None = None,
        performed_by: int | None = None,
    ) -> int:
        """Upgrade stored PDF presentation while preserving receipt identity and audit history."""
        query = Receipt.query.filter(Receipt.template_version != cls.TEMPLATE_VERSION)
        if tenant_id is not None:
            query = query.filter(Receipt.tenant_id == tenant_id)
        receipts = query.with_for_update().all()

        for receipt in receipts:
            previous_template_version = receipt.template_version
            previous_hash = receipt.document_sha256
            receipt.template_version = cls.TEMPLATE_VERSION
            document = cls._render_document(receipt)
            document_hash = hashlib.sha256(document).hexdigest()
            receipt.document_content = document
            receipt.document_sha256 = document_hash
            cls._audit(receipt, 'DOCUMENT_RESTYLED', performed_by, None, {
                'from_template_version': previous_template_version,
                'to_template_version': cls.TEMPLATE_VERSION,
                'previous_document_sha256': previous_hash,
                'document_sha256': document_hash,
            })
        db.session.info['allow_receipt_document_restyle'] = True
        try:
            db.session.execute(text("SET LOCAL app.allow_receipt_document_restyle = 'on'"))
            db.session.flush()
        finally:
            db.session.info.pop('allow_receipt_document_restyle', None)
        return len(receipts)

    @staticmethod
    def get_for_tenant(receipt_id: int, tenant_id: int) -> Receipt | None:
        return Receipt.query.filter_by(id=receipt_id, tenant_id=tenant_id).first()

    @classmethod
    def void(
        cls,
        receipt: Receipt,
        reason: str,
        voided_by: int | None,
        ip_address: str | None = None,
    ) -> Receipt:
        reason = str(reason or '').strip()
        if not reason:
            raise ValueError('void_reason is required.')
        if receipt.status == ReceiptStatus.VOIDED.value:
            return receipt
        if receipt.status != ReceiptStatus.ISSUED.value:
            raise ValueError('Only issued receipts can be voided.')
        receipt.status = ReceiptStatus.VOIDED.value
        receipt.voided_at = datetime.now(timezone.utc)
        receipt.voided_by = voided_by
        receipt.void_reason = reason[:255]
        cls._audit(receipt, 'VOIDED', voided_by, ip_address, {'reason': receipt.void_reason})
        return receipt

    @classmethod
    def record_access(cls, receipt: Receipt, action: str, performed_by: int | None, ip_address: str | None):
        cls._audit(receipt, action, performed_by, ip_address)

    @staticmethod
    def serialize(receipt: Receipt) -> dict:
        return {
            'id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'issued_at': receipt.issued_at.isoformat(),
            'issued_by': receipt.issued_by,
            'issued_at_display': receipt.issued_at.astimezone(timezone.utc).strftime('%d %b %Y, %I:%M %p UTC'),
            'status': receipt.status,
            'currency': receipt.currency,
            'template_version': receipt.template_version,
            'document_sha256': receipt.document_sha256,
            'voided_at': receipt.voided_at.isoformat() if receipt.voided_at else None,
            'voided_by': receipt.voided_by,
            'void_reason': receipt.void_reason,
            **receipt.snapshot,
        }

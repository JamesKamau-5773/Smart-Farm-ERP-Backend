from __future__ import annotations

from app.models.finance import TransactionAttachment
from app.utils.datetimes import iso


class TransactionAttachmentSerializer:
    @staticmethod
    def serialize(attachment: TransactionAttachment) -> dict:
        return {
            'id': attachment.id,
            'transaction_id': attachment.transaction_id,
            'content_type': attachment.content_type,
            'size_bytes': attachment.size_bytes,
            'filename': attachment.original_filename,
            'uploaded_by': attachment.uploaded_by,
            'uploaded_at': iso(attachment.uploaded_at),
            'url': f'/api/finance/transactions/{attachment.transaction_id}/attachments/{attachment.id}',
        }

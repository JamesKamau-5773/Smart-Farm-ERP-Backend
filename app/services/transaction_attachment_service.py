"""Receipt photos and documents attached to ledger entries.

Receipts carry financial details, so files live in private storage and are
served only through the tenant-scoped API. Attachments are append-only, like
the ledger they belong to.
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

from app.models.finance import TransactionAttachment
from app.repositories.ledger_repo import TransactionAttachmentRepository, TransactionRepository
from app.services.media_storage import MediaStorage, MediaStorageError
from app.utils.api_errors import ApiError
from app.utils.unit_of_work import unit_of_work
from app.utils.uploads import RECEIPT_CONTENT_TYPES, validate_receipt_upload

MAX_ATTACHMENTS_PER_ENTRY = 5


class TransactionAttachmentService:
    @staticmethod
    def upload(tenant_id: int, transaction_id: int, file_storage, *, uploaded_by: Optional[int]) -> TransactionAttachment:
        transaction = TransactionRepository.get_for_tenant(transaction_id, tenant_id)
        if transaction is None:
            raise ApiError('NOT_FOUND', 'Transaction not found.', 404)
        if file_storage is None or not getattr(file_storage, 'filename', None):
            raise ApiError('VALIDATION_ERROR', 'Attach the receipt as the "file" field.')
        if TransactionAttachmentRepository.count_for_transaction(transaction.id) >= MAX_ATTACHMENTS_PER_ENTRY:
            raise ApiError('ATTACHMENT_LIMIT', f'An entry can have at most {MAX_ATTACHMENTS_PER_ENTRY} attachments.', 409)
        try:
            extension, size = validate_receipt_upload(file_storage)
        except ValueError as exc:
            raise ApiError('VALIDATION_ERROR', str(exc))

        # Private: an authenticated Cloudinary file in production, the private folder locally.
        try:
            stored_path = MediaStorage.save_private(
                file_storage, folder=f'tenant_{tenant_id}', name=f'{transaction.id}_{uuid.uuid4().hex}', extension=extension,
            )
        except MediaStorageError:
            raise ApiError('STORAGE_UNAVAILABLE', "The receipt photo couldn't be stored. Try again.", 502)
        try:
            with unit_of_work():
                return TransactionAttachmentRepository.stage(TransactionAttachment(
                    tenant_id=tenant_id,
                    transaction_id=transaction.id,
                    stored_path=stored_path,
                    content_type=RECEIPT_CONTENT_TYPES[extension],
                    size_bytes=size,
                    original_filename=os.path.basename(file_storage.filename)[:255],
                    uploaded_by=uploaded_by,
                ))
        except Exception:
            MediaStorage.delete_private(stored_path)
            raise

    @staticmethod
    def open(tenant_id: int, transaction_id: int, attachment_id: int) -> tuple[TransactionAttachment, bytes]:
        """The attachment and its file's bytes (read from Cloudinary or the private folder)."""
        attachment = TransactionAttachmentRepository.get(tenant_id, transaction_id, attachment_id)
        if attachment is None:
            raise ApiError('NOT_FOUND', 'Attachment not found.', 404)
        content = MediaStorage.read_private(attachment.stored_path)
        if content is None:
            raise ApiError('NOT_FOUND', 'Attachment file is missing.', 404)
        return attachment, content

    @staticmethod
    def stage_copies(source, target) -> None:
        """Carries a corrected entry's attachments over to its replacement. The caller commits."""
        for attachment in source.attachments:
            TransactionAttachmentRepository.stage(TransactionAttachment(
                tenant_id=attachment.tenant_id,
                transaction_id=target.id,
                stored_path=attachment.stored_path,
                content_type=attachment.content_type,
                size_bytes=attachment.size_bytes,
                original_filename=attachment.original_filename,
                uploaded_by=attachment.uploaded_by,
                uploaded_at=attachment.uploaded_at,
            ))

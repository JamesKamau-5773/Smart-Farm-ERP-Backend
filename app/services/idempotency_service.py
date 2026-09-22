import hashlib
from datetime import datetime, timezone

from flask import Response
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.idempotency import IdempotencyRecord


class IdempotencyConflictError(ValueError):
    pass


class IdempotencyInProgressError(RuntimeError):
    pass


class IdempotencyService:
    MAX_KEY_LENGTH = 200

    @staticmethod
    def request_hash(method, path, body):
        fingerprint = b'\x00'.join((method.encode(), path.encode(), body))
        return hashlib.sha256(fingerprint).hexdigest()

    @classmethod
    def begin(cls, tenant_id, actor_id, key, method, path, body):
        key = (key or '').strip()
        if not key or len(key) > cls.MAX_KEY_LENGTH:
            raise ValueError('Idempotency-Key must contain 1 to 200 characters.')

        request_hash = cls.request_hash(method, path, body)
        record = IdempotencyRecord.query.filter_by(
            tenant_id=tenant_id,
            actor_id=str(actor_id),
            idempotency_key=key,
        ).first()
        if record:
            return cls._resolve_existing(record, request_hash)

        record = IdempotencyRecord(
            tenant_id=tenant_id,
            actor_id=str(actor_id),
            idempotency_key=key,
            request_method=method,
            request_path=path,
            request_hash=request_hash,
        )
        db.session.add(record)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            record = IdempotencyRecord.query.filter_by(
                tenant_id=tenant_id,
                actor_id=str(actor_id),
                idempotency_key=key,
            ).one()
            return cls._resolve_existing(record, request_hash)
        return record, None

    @staticmethod
    def _resolve_existing(record, request_hash):
        if record.request_hash != request_hash:
            raise IdempotencyConflictError(
                'This Idempotency-Key was already used with a different request.'
            )
        if record.status != 'COMPLETED':
            raise IdempotencyInProgressError(
                'A request with this Idempotency-Key is still processing.'
            )
        response = Response(
            record.response_body or '',
            status=record.response_status,
            mimetype=record.response_mimetype or 'application/json',
        )
        response.headers['Idempotency-Replayed'] = 'true'
        return record, response

    @staticmethod
    def complete(record_id, response):
        record = db.session.get(IdempotencyRecord, record_id)
        if not record:
            return
        if response.status_code >= 500:
            db.session.delete(record)
        else:
            record.status = 'COMPLETED'
            record.response_status = response.status_code
            record.response_body = response.get_data(as_text=True)
            record.response_mimetype = response.mimetype
            record.completed_at = datetime.now(timezone.utc)
        db.session.commit()
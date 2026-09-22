from datetime import datetime, timezone

from app import db


class IdempotencyRecord(db.Model):
    __tablename__ = 'idempotency_records'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    actor_id = db.Column(db.String(64), nullable=False)
    idempotency_key = db.Column(db.String(200), nullable=False)
    request_method = db.Column(db.String(10), nullable=False)
    request_path = db.Column(db.String(500), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='PROCESSING')
    response_status = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    response_mimetype = db.Column(db.String(100), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            'tenant_id',
            'actor_id',
            'idempotency_key',
            name='uq_idempotency_records_scope_key',
        ),
        db.CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED')",
            name='ck_idempotency_records_status',
        ),
    )
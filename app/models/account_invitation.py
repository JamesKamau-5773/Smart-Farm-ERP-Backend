from datetime import datetime, timezone

from app import db


class AccountInvitation(db.Model):
    """One-time, hashed invitation codes used in short claim URLs."""

    __tablename__ = 'account_invitations'

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    purpose = db.Column(db.String(40), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=True, index=True)
    employee_nonce = db.Column(db.String(32), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

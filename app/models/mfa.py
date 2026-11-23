"""Two-factor authentication (TOTP) for the platform admin."""
from datetime import datetime, timezone

from app import db


def _now():
    return datetime.now(timezone.utc)


class UserMfaCredential(db.Model):
    """One authenticator-app secret per user, encrypted at rest (app/utils/secret_cipher.py)."""
    __tablename__ = 'user_mfa_credentials'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    secret_ciphertext = db.Column(db.Text, nullable=False)
    # None while enrolment is started but not yet confirmed with a first code.
    confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # The last accepted TOTP time step; a code is never accepted twice.
    last_used_step = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)


class UserMfaRecoveryCode(db.Model):
    """Single-use recovery codes, stored only as keyed hashes (app/utils/secret_hashing.py)."""
    __tablename__ = 'user_mfa_recovery_codes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'code_hash', name='uq_user_mfa_recovery_codes_user_hash'),
    )


class MfaSession(db.Model):
    """Server-side record that the session with this token id passed 2FA."""
    __tablename__ = 'mfa_sessions'

    jti = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    method = db.Column(db.String(20), nullable=False)  # totp, recovery_code or enrolment
    verified_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

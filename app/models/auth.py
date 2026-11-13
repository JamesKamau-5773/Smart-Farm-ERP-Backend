from datetime import datetime, timezone

from app import db


def _utcnow():
    return datetime.now(timezone.utc)


def _as_aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class SocialAccount(db.Model):
    """A third-party identity (e.g. Google) linked to a local user."""

    __tablename__ = 'social_accounts'
    __table_args__ = (
        db.UniqueConstraint('provider', 'provider_user_id', name='uq_social_accounts_provider_subject'),
        db.UniqueConstraint('user_id', 'provider', name='uq_social_accounts_user_provider'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    provider = db.Column(db.String(32), nullable=False)
    provider_user_id = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship('User', backref=db.backref('social_accounts', lazy=True, cascade='all, delete-orphan'))


class ChallengePurpose:
    PHONE_VERIFICATION = 'phone_verification'
    PASSWORD_RESET_CODE = 'password_reset_code'
    PASSWORD_RESET_LINK = 'password_reset_link'
    EMAIL_VERIFICATION = 'email_verification'


class ChallengeStatus:
    PENDING = 'pending'
    VERIFIED = 'verified'
    EXPIRED = 'expired'
    LOCKED = 'locked'
    CANCELLED = 'cancelled'
    CONSUMED = 'consumed'


class VerificationChallenge(db.Model):
    """A hashed, expiring, attempt-limited one-time code or link token."""

    __tablename__ = 'verification_challenges'

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    purpose = db.Column(db.String(40), nullable=False)
    channel = db.Column(db.String(20), nullable=False)
    # E.164 phone or lowercased email the challenge proves possession of.
    target = db.Column(db.String(255), nullable=False)
    secret_hash = db.Column(db.String(64), nullable=False, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=5)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancelled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_inbound_message_id = db.Column(db.String(128), nullable=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.Index('ix_verification_challenges_lookup', 'purpose', 'target'),
    )

    @property
    def status(self) -> str:
        if self.cancelled_at:
            return ChallengeStatus.CANCELLED
        if self.consumed_at:
            return ChallengeStatus.CONSUMED
        if self.verified_at:
            return ChallengeStatus.VERIFIED
        if self.attempts >= self.max_attempts:
            return ChallengeStatus.LOCKED
        if _as_aware(self.expires_at) <= _utcnow():
            return ChallengeStatus.EXPIRED
        return ChallengeStatus.PENDING

    @property
    def is_pending(self) -> bool:
        return self.status == ChallengeStatus.PENDING

    @property
    def attempts_remaining(self) -> int:
        return max(self.max_attempts - self.attempts, 0)


class AccountDataIssueType:
    INVALID_PHONE = 'INVALID_PHONE'
    DUPLICATE_PHONE = 'DUPLICATE_PHONE'
    AMBIGUOUS_PHONE = 'AMBIGUOUS_PHONE'
    PHONE_RECLAIMED = 'PHONE_RECLAIMED'
    DUPLICATE_EMAIL = 'DUPLICATE_EMAIL'


class AccountDataIssue(db.Model):
    """Report of account data that could not be normalised automatically.

    Written by the auth-hardening migration and by phone reclamation; rows are
    never deleted so the original values stay recoverable.
    """

    __tablename__ = 'account_data_issues'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    field = db.Column(db.String(40), nullable=False)
    issue_type = db.Column(db.String(40), nullable=False)
    source = db.Column(db.String(40), nullable=True)
    raw_value = db.Column(db.String(255), nullable=True)
    normalized_value = db.Column(db.String(255), nullable=True)
    conflicting_user_id = db.Column(db.Integer, nullable=True)
    detected_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)

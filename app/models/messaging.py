import uuid
from datetime import datetime, timezone

from app import db


class ChatFlow:
    """Top-level WhatsApp workflows a farmhand can be inside."""
    LOG_MILK = 'log_milk'
    LOG_FEED = 'log_feed'
    VIEW_HERD = 'view_herd'
    VIEW_REPORTS = 'view_reports'


class ChatStep:
    """Steps within a ChatFlow, or the idle main-menu step."""
    MAIN_MENU = 'MAIN_MENU'
    AWAITING_COW_TAG = 'AWAITING_COW_TAG'
    AWAITING_SESSION = 'AWAITING_SESSION'
    AWAITING_MILK_YIELD = 'AWAITING_MILK_YIELD'
    AWAITING_CONFIRM = 'AWAITING_CONFIRM'


class ChatSession(db.Model):
    """Server-side conversation state for a WhatsApp farmhand, keyed by wa_id per tenant."""
    __tablename__ = 'user_chat_sessions'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey('farms.id', ondelete='SET NULL'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    wa_id = db.Column(db.String(20), nullable=False)
    current_flow = db.Column(db.String(50), nullable=True)
    current_step = db.Column(db.String(50), nullable=False, default=ChatStep.MAIN_MENU)
    expected_command_ids = db.Column(db.JSON, nullable=False, default=list)
    payload_context = db.Column(db.JSON, nullable=False, default=dict)
    last_message_id = db.Column(db.String(100), nullable=True)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'wa_id', name='uq_chat_sessions_tenant_wa_id'),
    )

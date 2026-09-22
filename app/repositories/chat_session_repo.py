from __future__ import annotations

from app import db
from app.models.messaging import ChatSession, ChatStep


class ChatSessionRepository:
    """Pure data access for WhatsApp conversation state. No business logic, no transport."""

    @staticmethod
    def get_by_wa_id(wa_id: str, tenant_id: int) -> ChatSession | None:
        return ChatSession.query.filter_by(wa_id=wa_id, tenant_id=tenant_id).first()

    @staticmethod
    def get_or_create(wa_id: str, tenant_id: int, user_id: int, farm_id: int | None = None) -> ChatSession:
        session = ChatSessionRepository.get_by_wa_id(wa_id, tenant_id)
        if session:
            return session
        session = ChatSession(
            tenant_id=tenant_id,
            farm_id=farm_id,
            user_id=user_id,
            wa_id=wa_id,
            current_flow=None,
            current_step=ChatStep.MAIN_MENU,
            expected_command_ids=[],
            payload_context={},
        )
        db.session.add(session)
        db.session.commit()
        return session

    @staticmethod
    def is_duplicate_message(session: ChatSession, message_id: str | None) -> bool:
        """True if this message id was already processed for this session (webhook retry)."""
        return bool(message_id) and session.last_message_id == message_id

    @staticmethod
    def advance(
        session: ChatSession,
        current_flow: str | None,
        current_step: str,
        payload_context: dict | None = None,
        expected_command_ids: list | None = None,
        message_id: str | None = None,
    ) -> ChatSession:
        session.current_flow = current_flow
        session.current_step = current_step
        if payload_context is not None:
            session.payload_context = payload_context
        session.expected_command_ids = expected_command_ids or []
        if message_id is not None:
            session.last_message_id = message_id
        db.session.commit()
        return session

    @staticmethod
    def touch_last_message_id(session: ChatSession, message_id: str | None) -> None:
        if message_id is not None:
            session.last_message_id = message_id
            db.session.commit()

    @staticmethod
    def reset(session: ChatSession, message_id: str | None = None) -> ChatSession:
        return ChatSessionRepository.advance(
            session, current_flow=None, current_step=ChatStep.MAIN_MENU,
            payload_context={}, expected_command_ids=[], message_id=message_id,
        )

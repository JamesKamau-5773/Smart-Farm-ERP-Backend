from __future__ import annotations

from app import db
from app.models.messaging import ChatFlow, ChatStep
from app.models.supply import MilkSession
from app.models.user import Role, User
from app.repositories.chat_session_repo import ChatSessionRepository
from app.repositories.cow_repo import CowRepository
from app.services import whatsapp_message_service as messages
from app.services.audit_service import record_audit
from app.services.production_service import ProductionService


class CommandId:
    """Stable option ids used across list rows/buttons. Never rename or reuse - labels are presentation only."""
    OPEN_MENU = 'open_menu'
    LOG_MILK = 'log_milk'
    LOG_FEED = 'log_feed'
    VIEW_HERD = 'view_herd'
    VIEW_REPORTS = 'view_reports'
    CONFIRM_YES = 'confirm_yes'
    CONFIRM_NO = 'confirm_no'
    SHIFT_MORNING = 'shift_morning'
    SHIFT_AFTERNOON = 'shift_afternoon'
    SHIFT_EVENING = 'shift_evening'


# Free-text synonyms that should behave like tapping "Menu" (users won't always tap buttons).
_MENU_TEXT_SYNONYMS = {'menu', 'cancel', 'restart'}

# Farmhand-facing roles allowed to drive farm actions over WhatsApp.
ALLOWED_ROLES = {Role.FARM_HAND, Role.FARM_MANAGER, Role.FARM_ADMIN, Role.FARMER, Role.SUPER_ADMIN, Role.ADMIN}

# WhatsApp UX offers Morning/Afternoon/Evening; the milk domain only distinguishes
# Morning/Midday/Evening, so "Afternoon" is mapped onto the existing Midday session.
_SHIFT_TO_MILK_SESSION = {
    CommandId.SHIFT_MORNING: MilkSession.MORNING,
    CommandId.SHIFT_AFTERNOON: MilkSession.MIDDAY,
    CommandId.SHIFT_EVENING: MilkSession.EVENING,
}

_MAX_HERD_LIST_ROWS = 15


def extract_command_id(message: dict) -> str:
    """Normalizes an inbound message to a stable command id. Never trust the display label."""
    interactive = message.get('interactive') or {}

    list_reply = interactive.get('list_reply')
    if list_reply:
        return list_reply.get('id', '') or ''

    button_reply = interactive.get('button_reply')
    if button_reply:
        return button_reply.get('id', '') or ''

    text = (message.get('text') or {}).get('body', '').strip().lower()
    if text in _MENU_TEXT_SYNONYMS:
        return CommandId.OPEN_MENU
    return text


def route_command(session, message: dict) -> dict:
    """Routes one inbound message for an already-deduped session. Returns an outbound message
    payload (see whatsapp_message_service builders). Never raises for domain/authorization
    errors - those become a text reply so the farmhand always gets a response."""
    user = db.session.get(User, session.user_id)
    if not user or not user.is_active or user.tenant_id != session.tenant_id:
        return messages.build_text_message("Your account is no longer active on this number.")

    if user.role not in ALLOWED_ROLES:
        return messages.build_text_message("This WhatsApp number is not authorized for farm actions.")

    command_id = extract_command_id(message)

    if command_id == CommandId.OPEN_MENU:
        ChatSessionRepository.reset(session)
        return messages.build_main_menu_message()

    handler = _STEP_HANDLERS.get(session.current_step, _handle_main_menu)
    return handler(session, user, command_id, message)


def _text_body(message: dict) -> str:
    return (message.get('text') or {}).get('body', '').strip()


def _handle_main_menu(session, user, command_id: str, message: dict) -> dict:
    if command_id == CommandId.LOG_MILK:
        ChatSessionRepository.advance(
            session, ChatFlow.LOG_MILK, ChatStep.AWAITING_COW_TAG,
            payload_context={}, expected_command_ids=[],
        )
        return messages.build_text_message("Please enter the cow's tag number.")

    if command_id == CommandId.VIEW_HERD:
        return _handle_view_herd(session, user)

    if command_id == CommandId.LOG_FEED:
        return messages.build_text_message("Feed logging via WhatsApp is coming soon.")

    if command_id == CommandId.VIEW_REPORTS:
        return messages.build_text_message("Reports via WhatsApp are coming soon. Please check the dashboard.")

    return messages.build_main_menu_message()


def _handle_awaiting_cow_tag(session, user, command_id: str, message: dict) -> dict:
    tag = _text_body(message)
    if not tag:
        return messages.build_text_message("Please type the cow's tag number.")

    cow = CowRepository.get_by_tag(tag, tenant_id=session.tenant_id)
    if not cow:
        return messages.build_text_message(f"No cow found with tag '{tag}'. Please try again, or reply MENU to cancel.")

    ChatSessionRepository.advance(
        session, ChatFlow.LOG_MILK, ChatStep.AWAITING_SESSION,
        payload_context={'cow_id': cow.id, 'tag_number': cow.tag_number},
        expected_command_ids=[CommandId.SHIFT_MORNING, CommandId.SHIFT_AFTERNOON, CommandId.SHIFT_EVENING],
    )
    return messages.build_session_buttons_message()


def _handle_awaiting_session(session, user, command_id: str, message: dict) -> dict:
    milk_session = _SHIFT_TO_MILK_SESSION.get(command_id)
    if not milk_session:
        return messages.build_session_buttons_message("Please tap Morning, Afternoon, or Evening below.")

    context = dict(session.payload_context or {})
    context['session'] = milk_session
    ChatSessionRepository.advance(
        session, ChatFlow.LOG_MILK, ChatStep.AWAITING_MILK_YIELD,
        payload_context=context, expected_command_ids=[],
    )
    return messages.build_text_message("Enter the milk yield in liters (e.g. 12.5).")


def _handle_awaiting_milk_yield(session, user, command_id: str, message: dict) -> dict:
    text = _text_body(message)
    try:
        amount = float(text)
    except ValueError:
        return messages.build_text_message("That doesn't look like a number. Please enter the milk yield in liters (e.g. 12.5).")

    if amount <= 0:
        return messages.build_text_message("Yield must be greater than zero. Please enter the milk yield in liters.")

    context = dict(session.payload_context or {})
    context['amount'] = amount
    ChatSessionRepository.advance(
        session, ChatFlow.LOG_MILK, ChatStep.AWAITING_CONFIRM,
        payload_context=context, expected_command_ids=[CommandId.CONFIRM_YES, CommandId.CONFIRM_NO],
    )
    return messages.build_confirm_buttons_message(
        f"Save {amount}L for {context.get('tag_number')} ({context.get('session')})?"
    )


def _handle_awaiting_confirm(session, user, command_id: str, message: dict) -> dict:
    if command_id == CommandId.CONFIRM_NO:
        ChatSessionRepository.reset(session)
        return messages.build_text_message("Cancelled. Reply MENU for more options.")

    if command_id != CommandId.CONFIRM_YES:
        return messages.build_confirm_buttons_message("Please tap Confirm or Cancel.")

    context = session.payload_context or {}
    cow_id = context.get('cow_id')
    tag_number = context.get('tag_number')
    milk_session = context.get('session')
    amount = context.get('amount')

    if not (cow_id and milk_session and amount):
        ChatSessionRepository.reset(session)
        return messages.build_text_message("Something went wrong with that entry. Please start again from the menu.")

    response = ProductionService.log_daily_yield(
        cow_id=cow_id, amount=amount, session=milk_session, user_id=user.id, tenant_id=session.tenant_id,
    )
    body, status_code = response
    ChatSessionRepository.reset(session)

    if status_code >= 400:
        error = body.get_json().get('error', 'Could not log the milk yield.')
        return messages.build_text_message(f"{error}\nReply MENU to try again.")

    log_id = body.get_json().get('log_id')
    record_audit(
        user_id=user.id, action='WHATSAPP_LOG_MILK', entity_type='MilkLog', entity_id=log_id,
        old_value=None, new_value=f"{amount}L {milk_session} for cow {cow_id} ({tag_number})",
        ip_address=f"whatsapp:{session.wa_id}",
    )
    db.session.commit()

    return messages.build_text_message(f"Logged {amount}L for {tag_number} ({milk_session}). Reply MENU for more options.")


def _handle_view_herd(session, user) -> dict:
    cows = CowRepository.get_all_active_livestock(tenant_id=session.tenant_id)
    record_audit(
        user_id=user.id, action='WHATSAPP_VIEW_HERD', entity_type='Tenant', entity_id=session.tenant_id,
        old_value=None, new_value=f"{len(cows)} active animals", ip_address=f"whatsapp:{session.wa_id}",
    )
    db.session.commit()

    if not cows:
        return messages.build_text_message("No active animals found. Reply MENU for more options.")

    lines = [f"- {cow.tag_number} ({cow.current_status})" for cow in cows[:_MAX_HERD_LIST_ROWS]]
    suffix = "\n...and more" if len(cows) > _MAX_HERD_LIST_ROWS else ""
    return messages.build_text_message("Active herd:\n" + "\n".join(lines) + suffix + "\n\nReply MENU for more options.")


_STEP_HANDLERS = {
    ChatStep.MAIN_MENU: _handle_main_menu,
    ChatStep.AWAITING_COW_TAG: _handle_awaiting_cow_tag,
    ChatStep.AWAITING_SESSION: _handle_awaiting_session,
    ChatStep.AWAITING_MILK_YIELD: _handle_awaiting_milk_yield,
    ChatStep.AWAITING_CONFIRM: _handle_awaiting_confirm,
}

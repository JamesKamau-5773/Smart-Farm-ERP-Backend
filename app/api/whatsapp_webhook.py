from flask import Blueprint, current_app, jsonify, request

from app.models.farm import Farm
from app.models.user import User
from app.repositories.chat_session_repo import ChatSessionRepository
from app.services import whatsapp_message_service as messages
from app.services.whatsapp_command_router import route_command
from app.utils.decorators import verify_whatsapp_signature
from app.utils.phone import normalize_phone

whatsapp_bp = Blueprint('whatsapp', __name__, url_prefix='/api/whatsapp')


@whatsapp_bp.route('/webhook', methods=['GET'])
def verify_webhook():
    """Meta's one-time webhook subscription handshake."""
    verify_token = current_app.config.get('WHATSAPP_VERIFY_TOKEN')
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge', '')

    if mode == 'subscribe' and verify_token and token == verify_token:
        return challenge, 200
    return jsonify({"error": "Forbidden"}), 403


def _resolve_farm_id(tenant_id: int):
    """Best-effort single-farm resolution; Cow/User have no farm_id yet, so this is
    persisted for forward-compatibility but not used to filter queries today."""
    farms = Farm.query.filter_by(tenant_id=tenant_id, is_active=True).limit(2).all()
    return farms[0].id if len(farms) == 1 else None


def _iter_inbound_messages(payload: dict):
    for entry in payload.get('entry', []) or []:
        for change in entry.get('changes', []) or []:
            value = change.get('value', {}) or {}
            for message in value.get('messages', []) or []:
                yield message


@whatsapp_bp.route('/webhook', methods=['POST'])
@verify_whatsapp_signature
def receive_webhook():
    """
    Public webhook for the Meta WhatsApp Cloud API. Only handles HTTP
    verification and inbound parsing/dedup/scope resolution - all command
    routing and domain logic lives in whatsapp_command_router.
    """
    payload = request.get_json(force=True, silent=True) or {}

    for message in _iter_inbound_messages(payload):
        message_id = message.get('id')
        wa_id = normalize_phone(message.get('from', ''))
        if not wa_id:
            continue

        user = User.query.filter_by(phone_number=wa_id, is_active=True).first()
        if not user:
            current_app.logger.warning(f"WhatsApp message from unregistered number: {wa_id}")
            continue

        session = ChatSessionRepository.get_or_create(
            wa_id, tenant_id=user.tenant_id, user_id=user.id, farm_id=_resolve_farm_id(user.tenant_id),
        )

        if ChatSessionRepository.is_duplicate_message(session, message_id):
            continue

        reply = route_command(session, message)
        ChatSessionRepository.touch_last_message_id(session, message_id)
        messages.send_message(wa_id, reply)

    return "OK", 200

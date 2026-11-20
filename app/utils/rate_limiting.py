from flask import g, request
from flask_jwt_extended import get_jwt_identity

def tenant_based_key_func():
    """
    Limits requests based on the tenant_id in the global context.
    Falls back to IP address for unauthenticated routes like /login.
    """
    if hasattr(g, 'tenant_id') and g.tenant_id:
        try:
            user_id = get_jwt_identity()
        except RuntimeError:
            user_id = None
        if user_id:
            return f"tenant:{g.tenant_id}:user:{user_id}"
        return f"tenant:{g.tenant_id}"

    return request.remote_addr


def _json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _normalized_contact(value) -> str:
    from app.utils.phone import try_to_e164

    value = str(value or '').strip()
    if not value:
        return ''
    if '@' in value:
        return value.lower()
    return try_to_e164(value) or value.lower()


def login_identifier_key():
    """Per-account throttle for login, independent of the caller's IP."""
    body = _json_body()
    raw = body.get('login') or body.get('email') or body.get('phone_number') or body.get('username')
    contact = _normalized_contact(raw)
    return f"login:{contact}" if contact else f"ip:{request.remote_addr}"


def recovery_contact_key():
    """Per-phone/per-email throttle for recovery and verification requests."""
    body = _json_body()
    contact = _normalized_contact(body.get('phone_number') or body.get('email'))
    return f"contact:{contact}" if contact else f"ip:{request.remote_addr}"


def authenticated_user_key():
    try:
        user_id = get_jwt_identity()
    except RuntimeError:
        user_id = None
    return f"user:{user_id}" if user_id else f"ip:{request.remote_addr}"

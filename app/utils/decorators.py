import hashlib
import hmac
from functools import wraps
from flask_jwt_extended import get_jwt, verify_jwt_in_request
from flask import current_app, jsonify, g, request
from app.models.user import Role


ELEVATED_ROLE_SET = {"ADMIN", "FARMER", "SUPER_ADMIN", "FARM_ADMIN"}
ROLE_INHERITANCE = {
    Role.FARM_MANAGER: {Role.FARM_MANAGER, Role.FARM_SUPERVISOR, Role.FARM_HAND},
    Role.FARM_SUPERVISOR: {Role.FARM_SUPERVISOR, Role.FARM_HAND},
}


def _normalize_role(value):
    return (value or "").strip().upper()


def _expand_effective_roles(role_value):
    role = _normalize_role(role_value)
    if not role:
        return set()
    if role in ELEVATED_ROLE_SET:
        # Farmer/SuperAdmin are treated as equivalent for endpoint access.
        return set(ELEVATED_ROLE_SET)
    return ROLE_INHERITANCE.get(role, {role})

def role_required(*required_roles):
    if len(required_roles) == 1 and isinstance(required_roles[0], (list, tuple, set)):
        required_roles = tuple(required_roles[0])
    required_role_set = {_normalize_role(role) for role in required_roles if role}

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            effective_roles = _expand_effective_roles(claims.get("role"))
                # Tenant administrators, farmers, and super admins have full platform access by policy.
            if effective_roles.intersection(ELEVATED_ROLE_SET):
                return fn(*args, **kwargs)
            if not effective_roles.intersection(required_role_set):
                return jsonify({"error": "Unauthorized. Authorization required."}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_tenant_context(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not getattr(g, 'tenant_id', None):
            return jsonify({"error": "Missing tenant context."}), 400
        return fn(*args, **kwargs)

    return wrapper


def optional_tenant_context(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request(optional=True)
        if getattr(g, 'tenant_id', None) is None:
            return jsonify({"error": "Missing tenant context."}), 400
        return fn(*args, **kwargs)

    return wrapper


def verify_whatsapp_signature(fn):
    """Validates Meta's X-Hub-Signature-256 HMAC before processing an inbound webhook."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        secret = current_app.config.get('WHATSAPP_APP_SECRET')
        signature = request.headers.get('X-Hub-Signature-256', '')
        if not secret:
            return jsonify({"error": "WhatsApp webhook is not configured."}), 503
        expected = 'sha256=' + hmac.new(secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return jsonify({"error": "Invalid signature."}), 403
        return fn(*args, **kwargs)

    return wrapper

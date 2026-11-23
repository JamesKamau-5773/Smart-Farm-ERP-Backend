import hashlib
import hmac
from functools import wraps
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask import current_app, jsonify, g, request
from app.models.user import Role


# Farm-level administrators: full access to their own tenant's farm routes. ADMIN is the
# cooperative admin (CooperativeService.create_cooperative). SUPER_ADMIN is deliberately absent:
# it never satisfies a role check; platform routes use platform_admin_required instead.
FARM_ADMIN_ROLES = frozenset({Role.FARMER, Role.FARM_ADMIN, Role.ADMIN})
ROLE_INHERITANCE = {
    Role.FARM_MANAGER: {Role.FARM_MANAGER, Role.FARM_SUPERVISOR, Role.FARM_HAND},
    Role.FARM_SUPERVISOR: {Role.FARM_SUPERVISOR, Role.FARM_HAND},
}


def _normalize_role(value):
    return (value or "").strip().upper()


def _expand_effective_roles(role_value):
    role = _normalize_role(role_value)
    if not role or role == Role.SUPER_ADMIN:
        return set()
    if role in FARM_ADMIN_ROLES:
        return set(FARM_ADMIN_ROLES)
    return ROLE_INHERITANCE.get(role, {role})


def _current_user():
    """The signed-in user, loaded live: roles are never taken from token claims."""
    from app import db
    from app.models.user import User

    identity = get_jwt_identity()
    try:
        return db.session.get(User, int(identity)) if identity is not None else None
    except (TypeError, ValueError):
        return None


def role_required(*required_roles):
    if len(required_roles) == 1 and isinstance(required_roles[0], (list, tuple, set)):
        required_roles = tuple(required_roles[0])
    required_role_set = {_normalize_role(role) for role in required_roles if role}

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user = _current_user()
            if user is None or not user.is_active:
                return jsonify({"error": "Unauthorized. Authorization required."}), 403
            effective_roles = _expand_effective_roles(user.role)
            if effective_roles & FARM_ADMIN_ROLES:
                return fn(*args, **kwargs)
            if effective_roles & required_role_set:
                return fn(*args, **kwargs)
            if user.role != Role.SUPER_ADMIN:
                # A farm owner may explicitly grant a page to a staff account;
                # honor that grant for the API routes belonging to that page.
                from app.services.page_access import grants, normalize_page_access, page_key_for_path
                page_key = page_key_for_path(request.path)
                granted_pages = normalize_page_access(user.page_access, user.role)
                if page_key and grants(granted_pages, page_key):
                    return fn(*args, **kwargs)
            return jsonify({"error": "Unauthorized. Authorization required."}), 403
        return wrapper
    return decorator


def platform_admin_required(fn):
    """Only the verified platform admin: the live SUPER_ADMIN, in the platform tenant, whose
    current session passed two-factor authentication (app/services/platform_access_service.py)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        from app.services.platform_access_service import PlatformAccessService

        if PlatformAccessService.current_platform_admin() is None:
            return jsonify({
                "code": "PLATFORM_ADMIN_REQUIRED",
                "error": "Only the platform admin can do this.",
            }), 403
        return fn(*args, **kwargs)
    return wrapper


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

from functools import wraps
from flask_jwt_extended import get_jwt, verify_jwt_in_request
from flask import jsonify, g


ELEVATED_ROLE_SET = {"FARMER", "ADMIN", "SUPER_ADMIN"}


def _normalize_role(value):
    return (value or "").strip().upper()


def _expand_effective_roles(role_value):
    role = _normalize_role(role_value)
    if not role:
        return set()
    if role in ELEVATED_ROLE_SET:
        # Farmer/Admin/SuperAdmin are treated as equivalent for endpoint access.
        return set(ELEVATED_ROLE_SET)
    return {role}

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
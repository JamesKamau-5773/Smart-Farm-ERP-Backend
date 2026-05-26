from functools import wraps
from flask_jwt_extended import get_jwt, verify_jwt_in_request
from flask import jsonify, g

def role_required(*required_roles):
    if len(required_roles) == 1 and isinstance(required_roles[0], (list, tuple, set)):
        required_roles = tuple(required_roles[0])

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get("role") not in required_roles:
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
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

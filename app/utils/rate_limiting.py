from flask import g, request

def tenant_based_key_func():
    """
    Limits requests based on the tenant_id in the global context.
    Falls back to IP address for unauthenticated routes like /login.
    """
    # If the middleware successfully set g.tenant_id from the JWT
    if hasattr(g, 'tenant_id') and g.tenant_id:
        return f"tenant:{g.tenant_id}"
    
    return request.remote_addr

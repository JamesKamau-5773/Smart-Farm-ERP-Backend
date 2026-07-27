from flask import g
from app.utils.jwt_payload import parse_public_int_id

def get_tenant_id_from_context():
    tenant_public_id = getattr(g, 'tenant_id', None)

    if not tenant_public_id:
        try:
            from flask_jwt_extended import get_jwt
            claims = get_jwt() or {}
            tenant_public_id = claims.get('tenant_id')
        except (RuntimeError, Exception):
            pass

    if not tenant_public_id:
        return None
        
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None

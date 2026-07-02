from flask import g
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request
from sqlalchemy import text
from app import db


def _parse_tenant_pk(tenant_id_value):
    if tenant_id_value is None:
        return None
    tenant_id_value = str(tenant_id_value).strip()
    if tenant_id_value.startswith("tenant_"):
        tenant_id_value = tenant_id_value[len("tenant_") :]
    try:
        return int(tenant_id_value)
    except ValueError:
        return None


def _looks_like_bearer_jwt(value):
    if not value:
        return False

    raw_value = str(value).strip()
    if not raw_value.lower().startswith('bearer '):
        return False

    token = raw_value[7:].strip()
    if not token or token.lower() in {'null', 'undefined', 'none'}:
        return False

    parts = token.split('.')
    return len(parts) == 3 and all(parts)


def _drop_invalid_authorization_header():
    try:
        from flask import request
    except Exception:
        return

    authorization_header = request.headers.get('Authorization')
    if authorization_header and not _looks_like_bearer_jwt(authorization_header):
        request.environ.pop('HTTP_AUTHORIZATION', None)

def set_tenant_context():
    """
    Sets the 'app.current_tenant_id' for the current database session and g.tenant_id.

    This function is executed before each request. It retrieves the tenant_id 
    from the JWT claims of the authenticated user and sets it as a 
    runtime parameter for the current PostgreSQL session. This is essential 
    for enforcing Row-Level Security (RLS) policies, ensuring that users 
    can only access data belonging to their tenant.

    If no user is authenticated (i.e., for public routes), this setting 
    is not applied, and access is determined by the default RLS behavior.
    """
    _drop_invalid_authorization_header()

    try:
        verify_jwt_in_request(optional=True)
    except Exception:
        return

    try:
        identity = get_jwt_identity()
    except RuntimeError:
        return
    if not identity:
        return

    try:
        claims = get_jwt() or {}
    except RuntimeError:
        return
    tenant_id = claims.get("tenant_id")
    farm_id = claims.get("farm_id")

    header_tenant_id = None
    header_farm_id = None
    header_cooperative_id = None
    try:
        from flask import request
        header_tenant_id = request.headers.get('X-Tenant-ID')
        header_farm_id = request.headers.get('X-Farm-ID')
        header_cooperative_id = request.headers.get('X-Cooperative-ID')
    except Exception:
        header_tenant_id = None
        header_farm_id = None
        header_cooperative_id = None

    if header_tenant_id:
        tenant_id = header_tenant_id
    if header_cooperative_id:
        tenant_id = header_cooperative_id
    if header_farm_id:
        farm_id = header_farm_id

    g.tenant_id = tenant_id
    g.cooperative_id = tenant_id
    g.farm_id = farm_id

    if tenant_id:
        try:
            tenant_pk = _parse_tenant_pk(tenant_id)
            if tenant_pk is not None:
                # Set the tenant_id for the current transaction (used by RLS)
                # Only supported/needed on PostgreSQL.
                if db.engine.dialect.name == 'postgresql':
                    db.session.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                        {"tenant_id": str(tenant_pk)},
                    )
        except Exception as e:
            print(f"Error setting tenant context: {e}")


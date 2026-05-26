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
    try:
        verify_jwt_in_request(optional=True)
    except Exception:
        return

    identity = get_jwt_identity()
    if not identity:
        return

    claims = get_jwt() or {}
    tenant_id = claims.get("tenant_id")
    g.tenant_id = tenant_id

    if tenant_id:
        try:
            tenant_pk = _parse_tenant_pk(tenant_id)
            if tenant_pk is not None:
                # Set the tenant_id for the current transaction (used by RLS)
                # Only supported/needed on PostgreSQL.
                if db.engine.dialect.name == 'postgresql':
                    db.session.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": str(tenant_pk)})
        except Exception as e:
            print(f"Error setting tenant context: {e}")


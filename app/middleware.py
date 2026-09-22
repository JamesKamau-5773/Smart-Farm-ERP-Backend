from flask import g, jsonify, request
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
    g.actor_id = None
    g.tenant_id = None
    g.cooperative_id = None
    g.farm_id = None

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

    g.actor_id = identity
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


def begin_idempotent_request():
    g.idempotency_record_id = None
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'} or not request.is_json:
        return None

    key = request.headers.get('Idempotency-Key')
    tenant_id = _parse_tenant_pk(getattr(g, 'tenant_id', None))
    actor_id = getattr(g, 'actor_id', None)
    if not key or tenant_id is None or actor_id is None:
        return None

    from app.services.idempotency_service import (
        IdempotencyConflictError,
        IdempotencyInProgressError,
        IdempotencyService,
    )

    try:
        record, replay = IdempotencyService.begin(
            tenant_id=tenant_id,
            actor_id=actor_id,
            key=key,
            method=request.method,
            path=request.full_path.rstrip('?'),
            body=request.get_data(cache=True),
        )
    except ValueError as error:
        return jsonify({'code': 'INVALID_IDEMPOTENCY_KEY', 'message': str(error)}), 422
    except IdempotencyConflictError as error:
        return jsonify({'code': 'IDEMPOTENCY_KEY_REUSED', 'message': str(error)}), 422
    except IdempotencyInProgressError as error:
        return jsonify({'code': 'IDEMPOTENCY_IN_PROGRESS', 'message': str(error)}), 409

    if replay is not None:
        return replay
    g.idempotency_record_id = record.id
    return None


def enforce_required_password_reset():
    actor_id = getattr(g, 'actor_id', None)
    if actor_id is None:
        return None

    allowed_endpoints = {
        'auth.login',
        'auth.register',
        'auth.claim_account',
        'auth.me',
        'auth.complete_password_reset',
        'auth.logout',
        'auth.status',
    }
    if request.endpoint in allowed_endpoints:
        return None

    from app.models.user import User

    try:
        user = db.session.get(User, int(actor_id))
    except (TypeError, ValueError):
        user = None
    if user and user.requires_password_reset:
        return jsonify({
            'code': 'PASSWORD_RESET_REQUIRED',
            'error': 'Password configuration is required before accessing this resource.',
        }), 403
    return None


def complete_idempotent_request(response):
    record_id = getattr(g, 'idempotency_record_id', None)
    if record_id is not None:
        from app.services.idempotency_service import IdempotencyService
        IdempotencyService.complete(record_id, response)
        response.headers['Idempotency-Replayed'] = 'false'
    return response


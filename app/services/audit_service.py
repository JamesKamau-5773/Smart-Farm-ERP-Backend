import json

from flask import has_request_context, request
from flask_jwt_extended import get_jwt_identity

from app import db
from app.models.audit import AuditLog

def record_audit(user_id, action, entity_type, entity_id, old_value, new_value, ip_address):
    """Creates and saves an audit log entry."""
    audit_log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=str(old_value),
        new_value=str(new_value),
        ip_address=ip_address
    )
    db.session.add(audit_log)
    # Note: The caller is responsible for committing the session.


def _request_actor_id():
    try:
        identity = get_jwt_identity()
    except RuntimeError:
        return None
    try:
        return int(identity) if identity is not None else None
    except (TypeError, ValueError):
        return None


def record_request_audit(action, entity_type, entity_id, old_value=None, new_value=None, *, commit=True):
    """Audit entry for the authenticated request's actor and IP address.

    Values are stored as JSON. Pass commit=False to stage the entry inside the
    caller's unit of work so it is saved atomically with the change.
    """
    audit_log = AuditLog(
        user_id=_request_actor_id(),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=json.dumps(old_value, default=str) if old_value is not None else None,
        new_value=json.dumps(new_value, default=str) if new_value is not None else None,
        ip_address=request.remote_addr if has_request_context() else None,
    )
    db.session.add(audit_log)
    if commit:
        db.session.commit()
    return audit_log

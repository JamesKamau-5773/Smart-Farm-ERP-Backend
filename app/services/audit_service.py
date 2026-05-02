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

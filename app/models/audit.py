from app import db
from datetime import datetime

class AuditLog(db.Model):
    """An immutable log of critical system actions."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # What happened?
    action = db.Column(db.String(50), nullable=False) # e.g., 'UPDATE_HARDLOCK', 'MANUAL_LEDGER_ENTRY'
    
    # What was affected?
    entity_type = db.Column(db.String(50), nullable=False) # e.g., 'Cow', 'Transaction'
    entity_id = db.Column(db.Integer, nullable=False)
    
    # Details and State
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    
    # Context
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', backref='actions_logged')
from app import db
from datetime import datetime

class Tenant(db.Model):
    __tablename__ = 'tenants'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    # 'single' or 'cooperative' 
    tenant_type = db.Column(db.String(20), default='single') 
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    farms = db.relationship('Farm', backref='tenant', lazy=True)
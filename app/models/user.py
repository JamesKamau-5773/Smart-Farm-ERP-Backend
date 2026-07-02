from app import db, bcrypt
from datetime import datetime, timezone


class Role:
    FARMER = "FARMER"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"
    FARM_HAND = "FARM_HAND"
    VET = "VETERINARY_DOCTOR"
    CUSTOMER = "CUSTOMER"


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    tenant = db.relationship('Tenant', backref='users', lazy=True)
    identifier = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    farm_location = db.Column(db.String(150), nullable=True)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default=Role.FARMER)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(
            password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

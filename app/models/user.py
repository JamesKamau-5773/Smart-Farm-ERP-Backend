from flask import current_app, has_app_context
from sqlalchemy import event, inspect
from sqlalchemy.orm import validates

from app import db, bcrypt
from app.utils.phone import normalize_phone
from datetime import datetime, timezone


class Role:
    FARMER = "FARMER"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"
    FARM_ADMIN = "FARM_ADMIN"
    FARM_MANAGER = "FARM_MANAGER"
    FARM_SUPERVISOR = "FARM_SUPERVISOR"
    FARM_HAND = "FARM_HAND"
    VET = "VETERINARY_DOCTOR"
    CUSTOMER = "CUSTOMER"

    @classmethod
    def assignable_farm_staff_roles(cls):
        return {
            cls.FARM_ADMIN,
            cls.FARM_MANAGER,
            cls.FARM_SUPERVISOR,
            cls.FARM_HAND,
            cls.VET,
        }

    @classmethod
    def assignable_tenant_member_roles(cls):
        return cls.assignable_farm_staff_roles() | {cls.FARMER}


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    tenant = db.relationship('Tenant', backref='users', lazy=True)
    identifier = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=True)
    farm_location = db.Column(db.String(150), nullable=True)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default=Role.FARMER)
    is_active = db.Column(db.Boolean, default=True)
    requires_password_reset = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(
            password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    @validates('phone_number')
    def _validate_phone_number(self, key, value):
        # Stored digits-only so it always matches WhatsApp's wa_id format.
        return normalize_phone(value) if value else value


class RevokedToken(db.Model):
    __tablename__ = 'revoked_tokens'

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def _super_admin_removal_allowed() -> bool:
    if not has_app_context():
        return False
    return bool(current_app.config.get('ALLOW_SUPER_ADMIN_REMOVAL', False))


@event.listens_for(User, 'before_delete')
def prevent_super_admin_delete(mapper, connection, target):
    if target.role == Role.SUPER_ADMIN and not _super_admin_removal_allowed():
        raise ValueError('Super Admin removal is disabled. Set ALLOW_SUPER_ADMIN_REMOVAL=True to override.')


@event.listens_for(User, 'before_update')
def prevent_super_admin_deactivation(mapper, connection, target):
    if target.role != Role.SUPER_ADMIN or _super_admin_removal_allowed():
        return

    state = inspect(target)
    if state.attrs.is_active.history.has_changes() and not target.is_active:
        raise ValueError('Super Admin cannot be deactivated. Set ALLOW_SUPER_ADMIN_REMOVAL=True to override.')

    if state.attrs.role.history.has_changes() and target.role != Role.SUPER_ADMIN:
        raise ValueError('Super Admin role cannot be changed. Set ALLOW_SUPER_ADMIN_REMOVAL=True to override.')

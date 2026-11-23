import secrets

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import validates

from app import db, bcrypt
from app.utils.phone import to_e164
from app.utils.super_admin_guard import SuperAdminChangeRefused, super_admin_changes_are_allowed
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
    page_access = db.Column(db.JSON, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    requires_password_reset = db.Column(db.Boolean, nullable=False, default=False)
    phone_verified = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    email_verified = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # False for accounts created through a social provider until a password is set.
    has_password = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    # Embedded in every access token; incrementing it revokes all live sessions.
    token_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    # Accounts belonging to the public demo workspace: no usable password, never
    # resolvable by the login or recovery flows, read-only when signed in.
    is_demo = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Case-insensitive email lookups for login and recovery.
        db.Index('ix_users_email_lower', db.func.lower(email)),
        # At most one SUPER_ADMIN, ever: the database is the final guard.
        db.Index(
            'uq_users_single_super_admin', 'role', unique=True,
            postgresql_where=db.text("role = 'SUPER_ADMIN'"),
        ),
    )

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(
            password).decode('utf-8')
        self.has_password = True

    def set_unusable_password(self):
        self.password_hash = bcrypt.generate_password_hash(secrets.token_urlsafe(32)).decode('utf-8')
        self.has_password = False

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    @property
    def needs_phone(self) -> bool:
        return not self.phone_number

    @validates('phone_number')
    def _validate_phone_number(self, key, value):
        # Stored in E.164; raises InvalidPhoneNumber for unparseable input.
        return to_e164(value) if value else None

    @validates('email')
    def _validate_email(self, key, value):
        value = (value or '').strip().lower()
        return value or None


class RevokedToken(db.Model):
    __tablename__ = 'revoked_tokens'

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def _tenant_is_platform(connection, tenant_id) -> bool:
    if tenant_id is None:
        return False
    from app.models.tenant import Tenant

    tenants = Tenant.__table__
    return bool(connection.execute(
        select(tenants.c.is_platform).where(tenants.c.id == tenant_id)
    ).scalar())


def _check_placement(connection, target) -> None:
    """The SUPER_ADMIN lives in the platform tenant, and every active account there is the SUPER_ADMIN."""
    on_platform = _tenant_is_platform(connection, target.tenant_id)
    if target.role == Role.SUPER_ADMIN and not on_platform:
        raise SuperAdminChangeRefused('The super admin must belong to the platform tenant.')
    active = target.is_active is None or bool(target.is_active)
    if on_platform and active and target.role != Role.SUPER_ADMIN:
        raise SuperAdminChangeRefused('Only the super admin may hold an active account in the platform tenant.')


@event.listens_for(User, 'before_insert')
def guard_super_admin_insert(mapper, connection, target):
    if target.role == Role.SUPER_ADMIN and not super_admin_changes_are_allowed():
        raise SuperAdminChangeRefused('A super admin can only be created by the bootstrap or the platform CLI.')
    _check_placement(connection, target)


@event.listens_for(User, 'before_update')
def guard_super_admin_update(mapper, connection, target):
    state = inspect(target)
    role_history = state.attrs.role.history
    changed = any(
        getattr(state.attrs, name).history.has_changes() for name in ('role', 'tenant_id', 'is_active')
    )
    if not changed:
        return  # Password, profile and verification changes never touch these rules.

    was_super_admin = Role.SUPER_ADMIN in (role_history.deleted or ()) or (
        not role_history.has_changes() and target.role == Role.SUPER_ADMIN
    )
    if (was_super_admin or target.role == Role.SUPER_ADMIN) and not super_admin_changes_are_allowed():
        raise SuperAdminChangeRefused(
            'The super admin can only be moved, demoted or deactivated with the platform CLI.'
        )
    _check_placement(connection, target)


@event.listens_for(User, 'before_delete')
def guard_super_admin_delete(mapper, connection, target):
    if target.role == Role.SUPER_ADMIN and not super_admin_changes_are_allowed():
        raise SuperAdminChangeRefused('The super admin account cannot be deleted.')

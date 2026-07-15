from flask import current_app

from app import db
from app.models.user import User, Role


def _bootstrap_super_admin_defaults():
    return {
        'username': current_app.config.get('BOOTSTRAP_SUPER_ADMIN_USERNAME', 'Super Admin'),
        'password': current_app.config.get('BOOTSTRAP_SUPER_ADMIN_PASSWORD', 'Blandina5773.'),
        'name': current_app.config.get('BOOTSTRAP_SUPER_ADMIN_NAME', 'Super Admin'),
        'email': current_app.config.get('BOOTSTRAP_SUPER_ADMIN_EMAIL', 'superadmin@example.com'),
        'identifier': current_app.config.get('BOOTSTRAP_SUPER_ADMIN_IDENTIFIER', 'super_admin'),
    }

def seed_roles():
    """
    Ensures a Super Admin account exists on the first run.
    """
    farmer_exists = User.query.filter_by(role=Role.FARMER).first()
    if not farmer_exists:
        admin = User(
            username="jivu_admin",
            role=Role.FARMER
        )
        admin.set_password("JivuSecure2026!") # Farmer must change this on first login
        db.session.add(admin)
        db.session.commit()
        print("Backend: SuperAdmin created.")


def ensure_super_admin_account():
    """Create a permanent Super Admin account if it is missing."""
    from app.models.farm import Farm
    from app.models.tenant import Tenant

    defaults = _bootstrap_super_admin_defaults()

    super_admin = User.query.filter_by(
        username=defaults['username'],
        identifier=defaults['identifier'],
    ).first()
    if super_admin:
        if not super_admin.is_active:
            super_admin.is_active = True
        super_admin.username = defaults['username']
        super_admin.name = defaults['name']
        super_admin.email = defaults['email']
        super_admin.identifier = defaults['identifier']
        super_admin.role = Role.SUPER_ADMIN
        super_admin.set_password(defaults['password'])
        db.session.commit()
        return super_admin

    tenant = Tenant.query.filter_by(tenant_type='single').first()
    if tenant is None:
        tenant = Tenant(name='Default Tenant', tenant_type='single')
        db.session.add(tenant)
        db.session.flush()

    farm = Farm.query.filter_by(tenant_id=tenant.id).first()
    if farm is None:
        farm = Farm(tenant_id=tenant.id, name='Default Farm')
        db.session.add(farm)
        db.session.flush()

    super_admin = User(
        tenant_id=tenant.id,
        identifier=defaults['identifier'],
        username=defaults['username'],
        name=defaults['name'],
        email=defaults['email'],
        role=Role.SUPER_ADMIN,
        is_active=True,
    )
    super_admin.set_password(defaults['password'])
    db.session.add(super_admin)
    db.session.commit()
    return super_admin
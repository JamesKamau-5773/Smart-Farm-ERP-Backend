"""Platform tenant and a single SUPER_ADMIN.

Revision ID: q9b0c1d2e3f4
Revises: p8a9b0c1d2e3
Create Date: 2026-11-23

* ``tenants.is_platform`` marks the platform workspace that houses the super admin.
  At most one exists, and it is never the demo workspace.
* One platform tenant row is inserted. It has no farm.
* ``uq_users_single_super_admin`` allows at most one SUPER_ADMIN user. The upgrade
  first counts them (read-only) and stops, changing nothing, if there is more than one.
* ``audit_logs.user_id`` becomes nullable: server-side CLI actions have no user.

No existing row is updated or deleted. The existing super admin is not moved
here; the ``flask platform`` commands do that, after a dry run.
"""
from alembic import op
import sqlalchemy as sa


revision = 'q9b0c1d2e3f4'
down_revision = 'p8a9b0c1d2e3'
branch_labels = None
depends_on = None

PLATFORM_TENANT_NAME = 'Maziwa Smart Platform'


def upgrade():
    bind = op.get_bind()

    super_admins = bind.execute(sa.text("SELECT count(*) FROM users WHERE role = 'SUPER_ADMIN'")).scalar()
    if super_admins > 1:
        raise RuntimeError(
            f'Found {super_admins} users with role SUPER_ADMIN; at most one is allowed. Nothing was '
            'changed. Decide which account stays the super admin, change the others by hand, then '
            'deploy again.'
        )

    op.add_column('tenants', sa.Column('is_platform', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(
        'uq_tenants_single_platform', 'tenants', ['is_platform'], unique=True,
        postgresql_where=sa.text('is_platform'),
    )
    op.create_check_constraint('ck_tenants_platform_not_demo', 'tenants', 'NOT (is_platform AND is_demo)')

    op.create_index(
        'uq_users_single_super_admin', 'users', ['role'], unique=True,
        postgresql_where=sa.text("role = 'SUPER_ADMIN'"),
    )

    bind.execute(
        sa.text(
            "INSERT INTO tenants (name, tenant_type, is_active, is_demo, is_platform, created_at) "
            "VALUES (:name, 'single', true, false, true, now())"
        ),
        {'name': PLATFORM_TENANT_NAME},
    )

    op.alter_column('audit_logs', 'user_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    bind = op.get_bind()

    platform_id = bind.execute(sa.text('SELECT id FROM tenants WHERE is_platform')).scalar()
    if platform_id is not None:
        in_use = bind.execute(
            sa.text(
                'SELECT (SELECT count(*) FROM users WHERE tenant_id = :id)'
                ' + (SELECT count(*) FROM farms WHERE tenant_id = :id)'
            ),
            {'id': platform_id},
        ).scalar()
        if in_use:
            raise RuntimeError(
                'The platform tenant has users or farms. Move the super admin back to a farm tenant '
                'before downgrading; nothing was changed.'
            )

    null_actors = bind.execute(sa.text('SELECT count(*) FROM audit_logs WHERE user_id IS NULL')).scalar()
    if null_actors:
        raise RuntimeError(
            f'{null_actors} audit entries have no user (server-side commands). audit_logs.user_id '
            'cannot become NOT NULL again without deleting them; nothing was changed.'
        )

    op.alter_column('audit_logs', 'user_id', existing_type=sa.Integer(), nullable=False)
    if platform_id is not None:
        # The only row this revision added.
        bind.execute(sa.text('DELETE FROM tenants WHERE id = :id AND is_platform'), {'id': platform_id})
    op.drop_index('uq_users_single_super_admin', table_name='users')
    op.drop_constraint('ck_tenants_platform_not_demo', 'tenants', type_='check')
    op.drop_index('uq_tenants_single_platform', table_name='tenants')
    op.drop_column('tenants', 'is_platform')

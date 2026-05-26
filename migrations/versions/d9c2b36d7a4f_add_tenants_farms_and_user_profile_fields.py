"""Add tenants, farms, and user profile fields

Revision ID: d9c2b36d7a4f
Revises: 390d029aa1ce
Create Date: 2026-05-13

This migration aligns the database schema with the current multi-tenant model:
- Adds tenants and farms tables
- Extends users with tenant linkage + identifier + name/email

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9c2b36d7a4f'
down_revision = '390d029aa1ce'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(sa.text("SELECT to_regclass(:t)"), {"t": f"public.{table_name}"}).scalar()
    return result is not None


def _column_names(conn, table_name: str) -> set[str]:
    rows = conn.execute(
        sa.text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :t
            """
        ),
        {"t": table_name},
    ).fetchall()
    return {r[0] for r in rows}


def upgrade():
    conn = op.get_bind()

    if not _table_exists(conn, 'tenants'):
        op.create_table(
            'tenants',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('tenant_type', sa.String(length=20), nullable=False, server_default='single'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if not _table_exists(conn, 'farms'):
        op.create_table(
            'farms',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_farms_tenant_id', 'farms', ['tenant_id'], unique=False)

    # Extend users table to include multi-tenant/profile fields.
    if _table_exists(conn, 'users'):
        existing = _column_names(conn, 'users')

        with op.batch_alter_table('users', schema=None) as batch_op:
            if 'tenant_id' not in existing:
                batch_op.add_column(sa.Column('tenant_id', sa.Integer(), nullable=True))
            if 'identifier' not in existing:
                batch_op.add_column(sa.Column('identifier', sa.String(length=100), nullable=True))
                batch_op.create_unique_constraint('uq_users_identifier', ['identifier'])
            if 'name' not in existing:
                batch_op.add_column(sa.Column('name', sa.String(length=120), nullable=True))
            if 'email' not in existing:
                batch_op.add_column(sa.Column('email', sa.String(length=120), nullable=True))
                batch_op.create_unique_constraint('uq_users_email', ['email'])

        # Seed a default tenant and farm if needed.
        tenant_id = conn.execute(sa.text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()
        if tenant_id is None:
            conn.execute(
                sa.text("INSERT INTO tenants (name, tenant_type, is_active) VALUES (:n, :t, true) RETURNING id"),
                {"n": "Default Tenant", "t": "single"},
            )
            tenant_id = conn.execute(sa.text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()

        farm_id = conn.execute(sa.text("SELECT id FROM farms WHERE tenant_id = :tid ORDER BY id LIMIT 1"), {"tid": tenant_id}).scalar()
        if farm_id is None:
            conn.execute(
                sa.text("INSERT INTO farms (tenant_id, name, is_active) VALUES (:tid, :n, true)"),
                {"tid": tenant_id, "n": "Default Farm"},
            )

        # Backfill existing user rows
        conn.execute(sa.text("UPDATE users SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": tenant_id})
        conn.execute(sa.text("UPDATE users SET identifier = username WHERE identifier IS NULL"))

        # Enforce NOT NULL where possible
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.alter_column('tenant_id', existing_type=sa.Integer(), nullable=False)
            batch_op.alter_column('identifier', existing_type=sa.String(length=100), nullable=False)
            # Add FK if not already present (best effort)
            try:
                batch_op.create_foreign_key('fk_users_tenant_id_tenants', 'tenants', ['tenant_id'], ['id'])
            except Exception:
                pass


def downgrade():
    conn = op.get_bind()

    if _table_exists(conn, 'users'):
        existing = _column_names(conn, 'users')
        with op.batch_alter_table('users', schema=None) as batch_op:
            for constraint in ['fk_users_tenant_id_tenants', 'uq_users_identifier', 'uq_users_email']:
                try:
                    batch_op.drop_constraint(constraint, type_='foreignkey' if constraint.startswith('fk_') else 'unique')
                except Exception:
                    pass

            for col in ['email', 'name', 'identifier', 'tenant_id']:
                if col in existing:
                    batch_op.drop_column(col)

    if _table_exists(conn, 'farms'):
        try:
            op.drop_index('ix_farms_tenant_id', table_name='farms')
        except Exception:
            pass
        op.drop_table('farms')

    if _table_exists(conn, 'tenants'):
        op.drop_table('tenants')

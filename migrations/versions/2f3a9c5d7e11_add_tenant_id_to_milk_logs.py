"""Add tenant_id to milk_logs for tenant isolation.

Revision ID: 2f3a9c5d7e11
Revises: 6a7d2f1b9c4e
Create Date: 2026-05-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '2f3a9c5d7e11'
down_revision = '6a7d2f1b9c4e'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    return conn.execute(sa.text("SELECT to_regclass(:t)"), {"t": f"public.{table_name}"}).scalar() is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    return conn.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
            """
        ),
        {"table": table_name, "column": column_name},
    ).scalar() is not None


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'milk_logs'):
        return

    if not _column_exists(conn, 'milk_logs', 'tenant_id'):
        op.add_column('milk_logs', sa.Column('tenant_id', sa.Integer(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE milk_logs AS ml
            SET tenant_id = u.tenant_id
            FROM users AS u
            WHERE ml.recorded_by = u.id
              AND ml.tenant_id IS NULL
            """
        )
    )

    missing = conn.execute(sa.text("SELECT COUNT(*) FROM milk_logs WHERE tenant_id IS NULL")).scalar() or 0
    if missing:
        raise RuntimeError(f"Cannot backfill milk_logs.tenant_id for {missing} rows.")

    op.alter_column('milk_logs', 'tenant_id', nullable=False)
    op.create_foreign_key(
        'fk_milk_logs_tenant_id_tenants',
        'milk_logs',
        'tenants',
        ['tenant_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_index(op.f('ix_milk_logs_tenant_id'), 'milk_logs', ['tenant_id'], unique=False)


def downgrade():
    conn = op.get_bind()
    if not _table_exists(conn, 'milk_logs'):
        return

    if _column_exists(conn, 'milk_logs', 'tenant_id'):
        op.drop_index(op.f('ix_milk_logs_tenant_id'), table_name='milk_logs')
        op.drop_constraint('fk_milk_logs_tenant_id_tenants', 'milk_logs', type_='foreignkey')
        op.drop_column('milk_logs', 'tenant_id')

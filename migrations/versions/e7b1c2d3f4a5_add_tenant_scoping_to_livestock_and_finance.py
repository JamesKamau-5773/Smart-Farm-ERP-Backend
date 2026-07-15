"""Add tenant scoping to livestock and finance roots

Revision ID: e7b1c2d3f4a5
Revises: 1c9c4f7e2d11, 4a1d7e9c2b33, 5e8c2b6f4d71, 7c9d1d3a4f11, c2d9e7a1f4b6, d4f6c1a8b2e7
Create Date: 2026-07-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7b1c2d3f4a5'
down_revision = '3f8e2a9c7d41'
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


def _enable_rls(conn, table_name: str):
    if not _table_exists(conn, table_name):
        return
    if not _column_exists(conn, table_name, 'tenant_id'):
        return
    op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table_name};"))
    op.execute(
        sa.text(
            f"""
            CREATE POLICY tenant_isolation_policy ON {table_name}
                USING (tenant_id = current_setting('app.current_tenant_id')::integer);
            """
        )
    )


def _first_tenant_id(conn):
    return conn.execute(sa.text("SELECT id FROM tenants ORDER BY id ASC LIMIT 1")).scalar()


def upgrade():
    conn = op.get_bind()
    first_tenant_id = _first_tenant_id(conn)

    tables = [
        'cows',
        'customers',
        'transactions',
        'medical_records',
    ]

    for table_name in tables:
        if not _table_exists(conn, table_name):
            continue
        if not _column_exists(conn, table_name, 'tenant_id'):
            op.add_column(table_name, sa.Column('tenant_id', sa.Integer(), nullable=True))
            op.create_index(op.f('ix_%s_tenant_id' % table_name), table_name, ['tenant_id'], unique=False)

    if _table_exists(conn, 'cows') and _column_exists(conn, 'cows', 'tenant_id') and first_tenant_id is not None:
        conn.execute(sa.text("UPDATE cows SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), {'tenant_id': first_tenant_id})
        op.alter_column('cows', 'tenant_id', existing_type=sa.Integer(), nullable=False)

    if _table_exists(conn, 'customers') and _column_exists(conn, 'customers', 'tenant_id') and first_tenant_id is not None:
        conn.execute(sa.text("UPDATE customers SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), {'tenant_id': first_tenant_id})
        op.alter_column('customers', 'tenant_id', existing_type=sa.Integer(), nullable=False)

    if _table_exists(conn, 'transactions') and _column_exists(conn, 'transactions', 'tenant_id'):
        if _table_exists(conn, 'users'):
            conn.execute(
                sa.text(
                    """
                    UPDATE transactions
                    SET tenant_id = users.tenant_id
                    FROM users
                    WHERE transactions.tenant_id IS NULL
                      AND transactions.recorded_by = users.id
                    """
                )
            )
        if first_tenant_id is not None:
            conn.execute(sa.text("UPDATE transactions SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), {'tenant_id': first_tenant_id})
        op.alter_column('transactions', 'tenant_id', existing_type=sa.Integer(), nullable=False)

    if _table_exists(conn, 'medical_records') and _column_exists(conn, 'medical_records', 'tenant_id'):
        if _table_exists(conn, 'cows'):
            conn.execute(
                sa.text(
                    """
                    UPDATE medical_records
                    SET tenant_id = cows.tenant_id
                    FROM cows
                    WHERE medical_records.tenant_id IS NULL
                      AND medical_records.cow_id = cows.id
                    """
                )
            )
        if first_tenant_id is not None:
            conn.execute(sa.text("UPDATE medical_records SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), {'tenant_id': first_tenant_id})
        op.alter_column('medical_records', 'tenant_id', existing_type=sa.Integer(), nullable=False)

    for table_name in ['cows', 'customers', 'transactions', 'medical_records', 'buyers', 'sales_ledger']:
        _enable_rls(conn, table_name)


def downgrade():
    conn = op.get_bind()

    for table_name in ['cows', 'customers', 'transactions', 'medical_records', 'buyers', 'sales_ledger']:
        if not _table_exists(conn, table_name):
            continue
        if _column_exists(conn, table_name, 'tenant_id'):
            op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table_name};"))
            op.execute(sa.text(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;"))

    for table_name in ['medical_records', 'transactions', 'customers', 'cows']:
        if _table_exists(conn, table_name) and _column_exists(conn, table_name, 'tenant_id'):
            op.drop_index(op.f('ix_%s_tenant_id' % table_name), table_name=table_name)
            op.drop_column(table_name, 'tenant_id')

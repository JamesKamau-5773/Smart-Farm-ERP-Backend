"""Enable RLS and add tenant isolation policies

Revision ID: 390d029aa1ce
Revises: 61e87038aae8
Create Date: 2026-05-12 17:31:35.158749

This migration enables Row-Level Security (RLS) on PostgreSQL for multi-tenant data isolation.
RLS policies enforce tenant_id-based row filtering at the database level, preventing cross-tenant data leaks.

PRODUCTION SETUP REQUIRED:
1. PostgreSQL connection must use valid credentials in DATABASE_URL
2. Example: postgresql://postgres:secure_password@localhost:5433/jivu_farm_db
3. Middleware sets app.current_tenant_id session variable for RLS enforcement
4. Tables milk_yield and financial_transactions must have tenant_id columns
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '390d029aa1ce'
down_revision = '61e87038aae8'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    # Uses Postgres regclass lookup; returns NULL if missing.
    result = conn.execute(sa.text("SELECT to_regclass(:t)"), {"t": f"public.{table_name}"}).scalar()
    return result is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
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
    ).scalar()
    return result is not None


def upgrade():
    conn = op.get_bind()
    tables = ["milk_yield", "financial_transactions"]

    for table_name in tables:
        if not _table_exists(conn, table_name):
            continue
        if not _column_exists(conn, table_name, "tenant_id"):
            continue

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


def downgrade():
    conn = op.get_bind()
    tables = ["milk_yield", "financial_transactions"]

    for table_name in tables:
        if not _table_exists(conn, table_name):
            continue

        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table_name};"))
        op.execute(sa.text(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;"))

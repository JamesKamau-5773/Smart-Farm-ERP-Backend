"""Index ledger and milk entries by farm-local date for period totals.

Revision ID: l4d5e6f7a8b9
Revises: k3c4d5e6f7a8
Create Date: 2026-11-06

The expression must match app.utils.farm_time.local_date_sql exactly
(``CAST(timezone('Africa/Nairobi', timestamp) AS DATE)``) for the planner to use
it. If FARM_TIMEZONE is changed, recreate these indexes with the new zone.
"""
from alembic import op


revision = 'l4d5e6f7a8b9'
down_revision = 'k3c4d5e6f7a8'
branch_labels = None
depends_on = None

LOCAL_DATE = "(CAST(timezone('Africa/Nairobi', \"timestamp\") AS DATE))"


def upgrade():
    op.execute(
        f'CREATE INDEX IF NOT EXISTS ix_transactions_tenant_farm_local_date '
        f'ON transactions (tenant_id, farm_id, {LOCAL_DATE})'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS ix_milk_logs_tenant_local_date '
        f'ON milk_logs (tenant_id, {LOCAL_DATE})'
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS ix_milk_logs_tenant_local_date')
    op.execute('DROP INDEX IF EXISTS ix_transactions_tenant_farm_local_date')

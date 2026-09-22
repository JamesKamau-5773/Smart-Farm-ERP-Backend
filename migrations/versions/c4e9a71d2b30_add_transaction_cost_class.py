"""add transaction cost class

Revision ID: c4e9a71d2b30
Revises: f8c14d3a60b2
"""

from alembic import op
import sqlalchemy as sa


revision = 'c4e9a71d2b30'
down_revision = 'f8c14d3a60b2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('cost_class', sa.String(length=30), nullable=True))
    op.create_check_constraint(
        'ck_transactions_cost_class_valid',
        'transactions',
        "cost_class IS NULL OR cost_class IN ('COGS', 'CUSTOMER_ACQUISITION', 'OPERATING', 'CAPITAL')",
    )
    op.execute("""
        UPDATE transactions
        SET cost_class = CASE
            WHEN category IN ('FEED_PURCHASE', 'VET_FEES', 'LABOR_WAGES', 'UTILITIES', 'INVENTORY_WRITE_OFF') THEN 'COGS'
            WHEN category = 'EQUIPMENT_MAINTENANCE' THEN 'OPERATING'
            WHEN category = 'TRANSPORT' THEN 'OPERATING'
            ELSE 'OPERATING'
        END
        WHERE transaction_type = 'EXPENSE' AND cost_class IS NULL
    """)


def downgrade():
    op.drop_constraint('ck_transactions_cost_class_valid', 'transactions', type_='check')
    op.drop_column('transactions', 'cost_class')

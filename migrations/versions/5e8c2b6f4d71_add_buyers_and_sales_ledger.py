"""Add buyers and sales ledger tables.

Revision ID: 5e8c2b6f4d71
Revises: 2f3a9c5d7e11
Create Date: 2026-05-31 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '5e8c2b6f4d71'
down_revision = '2f3a9c5d7e11'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'buyers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('agreed_rate_per_liter', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_buyers_tenant_name'),
    )
    op.create_index(op.f('ix_buyers_tenant_id'), 'buyers', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_buyers_name'), 'buyers', ['name'], unique=False)

    op.create_table(
        'sales_ledger',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('buyer_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('liters_sold', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('total_cost', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('payment_status', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['buyer_id'], ['buyers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'buyer_id', 'date', name='uq_sales_ledger_tenant_buyer_date'),
        sa.CheckConstraint("payment_status IN ('PAID', 'UNPAID')", name='ck_sales_ledger_payment_status_valid'),
    )
    op.create_index(op.f('ix_sales_ledger_tenant_id'), 'sales_ledger', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_sales_ledger_buyer_id'), 'sales_ledger', ['buyer_id'], unique=False)
    op.create_index(op.f('ix_sales_ledger_date'), 'sales_ledger', ['date'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_sales_ledger_date'), table_name='sales_ledger')
    op.drop_index(op.f('ix_sales_ledger_buyer_id'), table_name='sales_ledger')
    op.drop_index(op.f('ix_sales_ledger_tenant_id'), table_name='sales_ledger')
    op.drop_table('sales_ledger')

    op.drop_index(op.f('ix_buyers_name'), table_name='buyers')
    op.drop_index(op.f('ix_buyers_tenant_id'), table_name='buyers')
    op.drop_table('buyers')

"""Add inventory, nutrition, and safety support tables.

Revision ID: 4a1d7e9c2b33
Revises: 3b7c9a2d8f1c
Create Date: 2026-07-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '4a1d7e9c2b33'
down_revision = '3b7c9a2d8f1c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_items', sa.Column('sku', sa.String(length=80), nullable=True))
    op.create_unique_constraint('uq_inventory_items_tenant_sku', 'inventory_items', ['tenant_id', 'sku'])

    op.add_column('herdsman_routine_template', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('herdsman_routine_template', sa.Column('checklist_items', sa.JSON(), nullable=True))

    op.create_table(
        'milk_drop_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('cow_id', sa.Integer(), nullable=False),
        sa.Column('alert_date', sa.Date(), nullable=False),
        sa.Column('missing_milk_liters', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='OPEN'),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('investigation_notes', sa.Text(), nullable=True),
        sa.Column('selected_reasons', sa.JSON(), nullable=True),
        sa.Column('investigated_by', sa.Integer(), nullable=True),
        sa.Column('investigated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['cow_id'], ['cows.id']),
        sa.ForeignKeyConstraint(['investigated_by'], ['users.id']),
        sa.CheckConstraint("status IN ('OPEN', 'INVESTIGATING', 'RESOLVED')", name='ck_milk_drop_alerts_status_valid'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_milk_drop_alerts_tenant_status_date', 'milk_drop_alerts', ['tenant_id', 'status', 'alert_date'], unique=False)


def downgrade():
    op.drop_index('ix_milk_drop_alerts_tenant_status_date', table_name='milk_drop_alerts')
    op.drop_table('milk_drop_alerts')

    op.drop_column('herdsman_routine_template', 'checklist_items')
    op.drop_column('herdsman_routine_template', 'notes')

    op.drop_constraint('uq_inventory_items_tenant_sku', 'inventory_items', type_='unique')
    op.drop_column('inventory_items', 'sku')
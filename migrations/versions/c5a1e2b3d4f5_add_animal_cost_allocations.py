"""add animal cost allocations

Revision ID: c5a1e2b3d4f5
Revises: c4e9a71d2b30
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = 'c5a1e2b3d4f5'
down_revision = 'c4e9a71d2b30'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'animal_cost_allocations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('cow_id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=False),
        sa.Column('cost_type', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('occurred_on', sa.Date(), nullable=False),
        sa.Column('attribution_method', sa.String(length=20), nullable=False, server_default='DIRECT'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_animal_cost_allocations_amount_positive'),
        sa.CheckConstraint("attribution_method IN ('DIRECT', 'ALLOCATED')", name='ck_animal_cost_allocations_attribution_method_valid'),
        sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transaction_id'),
    )
    op.create_index('ix_animal_cost_allocations_tenant_id', 'animal_cost_allocations', ['tenant_id'])
    op.create_index('ix_animal_cost_allocations_cow_id', 'animal_cost_allocations', ['cow_id'])
    op.create_index('ix_animal_cost_allocations_tenant_cow_date', 'animal_cost_allocations', ['tenant_id', 'cow_id', 'occurred_on'])


def downgrade():
    op.drop_index('ix_animal_cost_allocations_tenant_cow_date', table_name='animal_cost_allocations')
    op.drop_index('ix_animal_cost_allocations_cow_id', table_name='animal_cost_allocations')
    op.drop_index('ix_animal_cost_allocations_tenant_id', table_name='animal_cost_allocations')
    op.drop_table('animal_cost_allocations')

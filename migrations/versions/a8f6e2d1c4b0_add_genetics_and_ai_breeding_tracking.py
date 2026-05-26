"""Add genetics score and AI breeding tracking

Revision ID: a8f6e2d1c4b0
Revises: d9c2b36d7a4f
Create Date: 2026-05-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8f6e2d1c4b0'
down_revision = 'd9c2b36d7a4f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cows', sa.Column('genetic_score', sa.Integer(), nullable=True))

    op.create_table(
        'semen_inventory',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('bull_name', sa.String(length=100), nullable=False),
        sa.Column('straw_code', sa.String(length=50), nullable=False),
        sa.Column('breed', sa.String(length=50), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=True),
        sa.Column('cost', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('stock_level', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('traits_to_improve', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'straw_code', name='uq_semen_inventory_tenant_straw_code')
    )
    op.create_index('ix_semen_inventory_tenant_id', 'semen_inventory', ['tenant_id'], unique=False)

    op.create_table(
        'breeding_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('cow_id', sa.Integer(), nullable=False),
        sa.Column('semen_id', sa.Integer(), nullable=False),
        sa.Column('insemination_date', sa.Date(), nullable=False),
        sa.Column('expected_calving_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Pending'),
        sa.CheckConstraint("status IN ('Pending', 'Pregnant', 'Failed')", name='ck_breeding_logs_status_valid'),
        sa.ForeignKeyConstraint(['cow_id'], ['cows.id']),
        sa.ForeignKeyConstraint(['semen_id'], ['semen_inventory.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_breeding_logs_tenant_id', 'breeding_logs', ['tenant_id'], unique=False)
    op.create_index('ix_breeding_logs_cow_id', 'breeding_logs', ['cow_id'], unique=False)
    op.create_index('ix_breeding_logs_semen_id', 'breeding_logs', ['semen_id'], unique=False)


def downgrade():
    op.drop_index('ix_breeding_logs_semen_id', table_name='breeding_logs')
    op.drop_index('ix_breeding_logs_cow_id', table_name='breeding_logs')
    op.drop_index('ix_breeding_logs_tenant_id', table_name='breeding_logs')
    op.drop_table('breeding_logs')

    op.drop_index('ix_semen_inventory_tenant_id', table_name='semen_inventory')
    op.drop_table('semen_inventory')

    op.drop_column('cows', 'genetic_score')

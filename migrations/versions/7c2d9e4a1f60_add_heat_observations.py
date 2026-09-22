"""Add tenant-scoped heat observations

Revision ID: 7c2d9e4a1f60
Revises: 5a8c1e4d7b20
Create Date: 2026-08-28

"""
from alembic import op
import sqlalchemy as sa


revision = '7c2d9e4a1f60'
down_revision = '5a8c1e4d7b20'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'heat_observations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('cow_id', sa.Integer(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('intensity', sa.String(length=20), nullable=False),
        sa.Column('signs', sa.JSON(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('next_window_start', sa.Date(), nullable=False),
        sa.Column('next_window_end', sa.Date(), nullable=False),
        sa.Column('breeding_log_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("intensity IN ('LOW', 'MEDIUM', 'HIGH')", name='ck_heat_observations_intensity_valid'),
        sa.CheckConstraint('next_window_end >= next_window_start', name='ck_heat_observations_window_valid'),
        sa.ForeignKeyConstraint(['breeding_log_id'], ['breeding_logs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('breeding_log_id'),
    )
    op.create_index('ix_heat_observations_tenant_id', 'heat_observations', ['tenant_id'], unique=False)
    op.create_index('ix_heat_observations_cow_id', 'heat_observations', ['cow_id'], unique=False)
    op.create_index('ix_heat_observations_tenant_cow_observed', 'heat_observations', ['tenant_id', 'cow_id', 'observed_at'], unique=False)


def downgrade():
    op.drop_index('ix_heat_observations_tenant_cow_observed', table_name='heat_observations')
    op.drop_index('ix_heat_observations_cow_id', table_name='heat_observations')
    op.drop_index('ix_heat_observations_tenant_id', table_name='heat_observations')
    op.drop_table('heat_observations')

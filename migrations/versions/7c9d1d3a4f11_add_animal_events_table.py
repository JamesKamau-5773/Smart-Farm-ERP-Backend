"""Add animal events table

Revision ID: 7c9d1d3a4f11
Revises: b4f5c2a1d9e6
Create Date: 2026-07-02 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = '7c9d1d3a4f11'
down_revision = 'b4f5c2a1d9e6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'animal_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('cow_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('event_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event_data', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['cow_id'], ['cows.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_animal_events_tenant_id', 'animal_events', ['tenant_id'], unique=False)
    op.create_index('ix_animal_events_cow_id', 'animal_events', ['cow_id'], unique=False)
    op.create_index('ix_animal_events_created_by', 'animal_events', ['created_by'], unique=False)


def downgrade():
    op.drop_index('ix_animal_events_created_by', table_name='animal_events')
    op.drop_index('ix_animal_events_cow_id', table_name='animal_events')
    op.drop_index('ix_animal_events_tenant_id', table_name='animal_events')
    op.drop_table('animal_events')
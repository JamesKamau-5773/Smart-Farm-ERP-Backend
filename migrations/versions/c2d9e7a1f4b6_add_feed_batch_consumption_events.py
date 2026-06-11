"""Add feed batch consumption events for depletion workflow.

Revision ID: c2d9e7a1f4b6
Revises: 9f4d3b2c1a7e
Create Date: 2026-06-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c2d9e7a1f4b6'
down_revision = '9f4d3b2c1a7e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'feed_batch_consumption_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('consumed_weight', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('consumed_on', sa.Date(), nullable=False, server_default=sa.text('CURRENT_DATE')),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'batch_id'],
            ['feed_batches.tenant_id', 'feed_batches.id'],
            ondelete='CASCADE',
            name='fk_feed_batch_consumption_events_batch_tenant',
        ),
        sa.CheckConstraint('consumed_weight > 0', name='ck_feed_batch_consumption_events_weight_positive'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('ix_feed_batch_consumption_events_tenant_id', 'feed_batch_consumption_events', ['tenant_id'], unique=False)
    op.create_index('ix_feed_batch_consumption_events_batch_id', 'feed_batch_consumption_events', ['batch_id'], unique=False)
    op.create_index(
        'ix_feed_batch_consumption_events_tenant_batch_date',
        'feed_batch_consumption_events',
        ['tenant_id', 'batch_id', 'consumed_on'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_feed_batch_consumption_events_tenant_batch_date', table_name='feed_batch_consumption_events')
    op.drop_index('ix_feed_batch_consumption_events_batch_id', table_name='feed_batch_consumption_events')
    op.drop_index('ix_feed_batch_consumption_events_tenant_id', table_name='feed_batch_consumption_events')
    op.drop_table('feed_batch_consumption_events')

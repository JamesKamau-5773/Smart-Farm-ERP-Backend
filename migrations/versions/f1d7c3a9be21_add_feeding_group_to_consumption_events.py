"""add feeding group to consumption events

Revision ID: f1d7c3a9be21
Revises: ab6c2f91d440
Create Date: 2026-08-25 00:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1d7c3a9be21'
down_revision = 'ab6c2f91d440'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feed_batch_consumption_events', sa.Column('feeding_group', sa.String(length=40), nullable=True))
    op.create_check_constraint(
        'ck_feed_batch_consumption_events_feeding_group_valid',
        'feed_batch_consumption_events',
        "feeding_group IS NULL OR feeding_group IN ('lactating', 'dry', 'calf_0_3m', 'calf_3_6m', 'heifer')",
    )


def downgrade():
    op.drop_constraint('ck_feed_batch_consumption_events_feeding_group_valid', 'feed_batch_consumption_events', type_='check')
    op.drop_column('feed_batch_consumption_events', 'feeding_group')

"""add feeding group to feed recipes

Revision ID: ab6c2f91d440
Revises: e31a4d9b7c20
Create Date: 2026-08-25 00:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ab6c2f91d440'
down_revision = 'e31a4d9b7c20'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feed_recipes', sa.Column('feeding_group', sa.String(length=40), nullable=True))
    op.create_check_constraint(
        'ck_feed_recipes_feeding_group_valid',
        'feed_recipes',
        "feeding_group IS NULL OR feeding_group IN ('lactating', 'dry', 'calf_0_3m', 'calf_3_6m', 'heifer')",
    )


def downgrade():
    op.drop_constraint('ck_feed_recipes_feeding_group_valid', 'feed_recipes', type_='check')
    op.drop_column('feed_recipes', 'feeding_group')

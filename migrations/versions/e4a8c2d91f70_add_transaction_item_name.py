"""add transaction item name

Revision ID: e4a8c2d91f70
Revises: d6f30b8a2e14
"""

from alembic import op
import sqlalchemy as sa


revision = 'e4a8c2d91f70'
down_revision = 'd6f30b8a2e14'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('item_name', sa.String(length=120), nullable=True))


def downgrade():
    op.drop_column('transactions', 'item_name')

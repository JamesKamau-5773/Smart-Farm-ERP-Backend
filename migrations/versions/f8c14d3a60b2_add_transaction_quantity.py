"""add transaction quantity

Revision ID: f8c14d3a60b2
Revises: e4a8c2d91f70
"""

from alembic import op
import sqlalchemy as sa


revision = 'f8c14d3a60b2'
down_revision = 'e4a8c2d91f70'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=True))


def downgrade():
    op.drop_column('transactions', 'quantity')

"""Store the selected income category on customer payments.

Revision ID: f7b2c4d6e8a0
Revises: e6a1b2c3d4f5
Create Date: 2026-10-22 18:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f7b2c4d6e8a0'
down_revision = 'e6a1b2c3d4f5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('income_category', sa.String(length=30), nullable=True))


def downgrade():
    op.drop_column('transactions', 'income_category')

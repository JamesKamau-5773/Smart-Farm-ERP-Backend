"""Add farm location to users

Revision ID: b4f5c2a1d9e6
Revises: ae11c7a9b24d
Create Date: 2026-07-02 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'b4f5c2a1d9e6'
down_revision = 'ae11c7a9b24d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('farm_location', sa.String(length=150), nullable=True))


def downgrade():
    op.drop_column('users', 'farm_location')
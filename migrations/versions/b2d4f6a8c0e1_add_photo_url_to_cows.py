"""Add photo_url to cows

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-09-14
"""

from alembic import op
import sqlalchemy as sa


revision = 'b2d4f6a8c0e1'
down_revision = 'a1c3e5f7b9d2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cows', sa.Column('photo_url', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('cows', 'photo_url')

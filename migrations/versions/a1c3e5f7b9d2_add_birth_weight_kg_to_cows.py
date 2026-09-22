"""Add birth_weight_kg to cows

Revision ID: a1c3e5f7b9d2
Revises: f4b6c8d0e2a3
Create Date: 2026-09-14
"""

from alembic import op
import sqlalchemy as sa


revision = 'a1c3e5f7b9d2'
down_revision = 'f4b6c8d0e2a3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cows', sa.Column('birth_weight_kg', sa.Numeric(5, 2), nullable=True))


def downgrade():
    op.drop_column('cows', 'birth_weight_kg')

"""Add sire PTA snapshot to breeding logs.

Revision ID: c7e9a1b3d5f7
Revises: b6d8f0a2c4e5
Create Date: 2026-09-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c7e9a1b3d5f7'
down_revision = 'b6d8f0a2c4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('breeding_logs', sa.Column('sire_pta_scores', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('breeding_logs', 'sire_pta_scores')

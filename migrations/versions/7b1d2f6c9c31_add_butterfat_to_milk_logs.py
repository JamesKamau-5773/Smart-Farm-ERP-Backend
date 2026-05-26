"""Add butterfat to milk logs

Revision ID: 7b1d2f6c9c31
Revises: ea7d0c9f7b21
Create Date: 2026-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7b1d2f6c9c31'
down_revision = 'ea7d0c9f7b21'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('milk_logs', sa.Column('butterfat_pct', sa.Numeric(precision=5, scale=2), nullable=True))


def downgrade():
    op.drop_column('milk_logs', 'butterfat_pct')
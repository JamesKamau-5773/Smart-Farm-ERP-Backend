"""Merge heads bc34de56fa78 and f2b3c4d5e6a7

Revision ID: d1f840c1924f
Revises: bc34de56fa78, f2b3c4d5e6a7
Create Date: 2026-07-08 14:22:51.770577

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1f840c1924f'
down_revision = ('bc34de56fa78', 'f2b3c4d5e6a7')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

"""add milk log verification fields

Revision ID: c6d4e8f1a2b3
Revises: dca1b9eb738e
Create Date: 2026-07-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6d4e8f1a2b3'
down_revision = 'dca1b9eb738e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('milk_logs', sa.Column('verified_by', sa.Integer(), nullable=True))
    op.add_column('milk_logs', sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_milk_logs_verified_by_users',
        'milk_logs',
        'users',
        ['verified_by'],
        ['id'],
    )


def downgrade():
    op.drop_constraint('fk_milk_logs_verified_by_users', 'milk_logs', type_='foreignkey')
    op.drop_column('milk_logs', 'verified_at')
    op.drop_column('milk_logs', 'verified_by')
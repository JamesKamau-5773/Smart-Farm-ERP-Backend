"""Add is_active and updated_at to animal_yield_targets

Revision ID: f2b3c4d5e6a7
Revises: ab12cd34ef56
Create Date: 2026-07-07 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'f2b3c4d5e6a7'
down_revision = 'ab12cd34ef56'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'animal_yield_targets',
        sa.Column(
            'is_active',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
    )
    op.add_column(
        'animal_yield_targets',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )


def downgrade():
    op.drop_column('animal_yield_targets', 'updated_at')
    op.drop_column('animal_yield_targets', 'is_active')

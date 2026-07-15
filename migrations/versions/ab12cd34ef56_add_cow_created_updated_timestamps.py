"""Add persistent created_at and updated_at to cows

Revision ID: ab12cd34ef56
Revises: f1a2b3c4d5e6
Create Date: 2026-07-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'ab12cd34ef56'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'cows',
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    op.add_column(
        'cows',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )

    op.execute('UPDATE cows SET updated_at = COALESCE(updated_at, created_at)')


def downgrade():
    op.drop_column('cows', 'updated_at')
    op.drop_column('cows', 'created_at')

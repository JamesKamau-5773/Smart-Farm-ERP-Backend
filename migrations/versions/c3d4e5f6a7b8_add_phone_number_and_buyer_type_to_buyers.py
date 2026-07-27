"""add phone_number and buyer_type to buyers

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-17 00:00:02.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'buyers',
        sa.Column('phone_number', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'buyers',
        sa.Column(
            'buyer_type',
            sa.String(length=50),
            nullable=False,
            server_default='Individual',
        ),
    )


def downgrade():
    op.drop_column('buyers', 'buyer_type')
    op.drop_column('buyers', 'phone_number')

"""expand transaction description length

Revision ID: d7a4c9e12b63
Revises: 82485feb3602
Create Date: 2026-10-21 17:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7a4c9e12b63'
down_revision = '82485feb3602'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column(
            'description',
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column(
            'description',
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=True,
        )

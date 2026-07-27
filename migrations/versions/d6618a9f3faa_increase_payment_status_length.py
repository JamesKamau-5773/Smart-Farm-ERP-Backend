"""increase_payment_status_length

Revision ID: d6618a9f3faa
Revises: 432fc760513f
Create Date: 2026-07-21 15:46:20.137598

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd6618a9f3faa'
down_revision = '432fc760513f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sales_ledger', schema=None) as batch_op:
        batch_op.alter_column('payment_status',
                              existing_type=sa.VARCHAR(length=10),
                              type_=sa.VARCHAR(length=50))


def downgrade():
    with op.batch_alter_table('sales_ledger', schema=None) as batch_op:
        batch_op.alter_column('payment_status',
                              existing_type=sa.VARCHAR(length=50),
                              type_=sa.VARCHAR(length=10))

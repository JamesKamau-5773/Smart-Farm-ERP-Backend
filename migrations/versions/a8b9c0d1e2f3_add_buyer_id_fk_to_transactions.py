"""Add buyer_id FK to transactions

Revision ID: a8b9c0d1e2f3
Revises: 476856e73a89
Create Date: 2026-07-17 16:18:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8b9c0d1e2f3'
down_revision = '476856e73a89'
branch_labels = None
depends_on = None


def upgrade():
    # Add buyer_id column to transactions if it doesn't exist
    try:
        op.add_column('transactions', sa.Column('buyer_id', sa.Integer(), nullable=True))
        op.create_foreign_key('fk_transactions_buyer_id_buyers_id', 'transactions', 'buyers', ['buyer_id'], ['id'], ondelete='SET NULL')
    except Exception:
        # Column might already exist from schema synchronization
        pass


def downgrade():
    # Remove buyer_id foreign key and column
    try:
        op.drop_constraint('fk_transactions_buyer_id_buyers_id', 'transactions', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_column('transactions', 'buyer_id')
    except Exception:
        pass

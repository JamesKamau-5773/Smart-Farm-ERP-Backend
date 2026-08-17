"""Standardize enum data for transaction type and category.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-17 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    # Standardize 'Revenue' to 'REVENUE' for transaction_type
    op.execute("UPDATE transactions SET transaction_type = 'REVENUE' WHERE transaction_type = 'Revenue'")
    
    # Standardize 'Milk Sale' to 'MILK_SALE' for category
    op.execute("UPDATE transactions SET category = 'MILK_SALE' WHERE category = 'Milk Sale'")


def downgrade():
    # This is a data-only migration. A downgrade could revert the strings,
    # but it's safer to leave them in the standardized format as it's
    # functionally correct and avoids potential data loss if other
    # 'REVENUE' or 'MILK_SALE' records were created.
    pass
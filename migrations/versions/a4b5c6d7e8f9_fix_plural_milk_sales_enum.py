"""Fix plural 'Milk Sales' enum value in transactions.

Revision ID: a4b5c6d7e8f9
Revises: f9e8d7c6b5a4
Create Date: 2026-08-17 22:30:00.123456

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4b5c6d7e8f9'
down_revision = 'f9e8d7c6b5a4'
branch_labels = None
depends_on = None


def upgrade():
    """
    Standardizes the plural 'Milk Sales' string in the transaction category
    to the correct 'MILK_SALE' enum value, fixing a LookupError.
    """
    op.execute("UPDATE transactions SET category = 'MILK_SALE' WHERE category = 'Milk Sales'")


def downgrade():
    # A downgrade is not strictly necessary as it would re-introduce the error.
    pass
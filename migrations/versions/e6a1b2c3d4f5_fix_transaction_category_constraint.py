"""Fix transaction category check constraint for AI service expenses.

Revision ID: e6a1b2c3d4f5
Revises: d7a4c9e12b63
Create Date: 2026-10-22 18:00:00.000000
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e6a1b2c3d4f5'
down_revision = 'd7a4c9e12b63'
branch_labels = None
depends_on = None


_TRANSACTION_CATEGORIES = (
    'MILK_SALE', 'LIVESTOCK_SALE', 'OTHER_INCOME', 'PAYMENT',
    'INVENTORY_WRITE_OFF', 'OTHER', 'FEED_PURCHASE', 'VET_FEES',
    'AI_SERVICE', 'LABOR_WAGES', 'UTILITIES', 'EQUIPMENT_MAINTENANCE',
    'TRANSPORT', 'OPENING_BALANCE', 'BUYER_PAYMENT',
)


def _category_check(values):
    quoted_values = ', '.join("'{}'".format(value) for value in values)
    return 'category IN ({})'.format(quoted_values)


def upgrade():
    # The initial schema created a VARCHAR-backed enum, which PostgreSQL
    # represents as a check constraint. Later enum alterations can leave the
    # original check in place, so replace it explicitly.
    op.drop_constraint('transactioncategory', 'transactions', type_='check')
    op.create_check_constraint(
        'transactioncategory',
        'transactions',
        _category_check(_TRANSACTION_CATEGORIES),
    )


def downgrade():
    previous_categories = tuple(
        value for value in _TRANSACTION_CATEGORIES if value != 'AI_SERVICE'
    )
    op.drop_constraint('transactioncategory', 'transactions', type_='check')
    op.create_check_constraint(
        'transactioncategory',
        'transactions',
        _category_check(previous_categories),
    )

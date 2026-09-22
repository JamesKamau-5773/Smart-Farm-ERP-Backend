"""Add ledger counterparty and payment method

Revision ID: 5a8c1e4d7b20
Revises: 4e7c9a1b2d3f
Create Date: 2026-08-28

"""
from alembic import op
import sqlalchemy as sa


revision = '5a8c1e4d7b20'
down_revision = '4e7c9a1b2d3f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('counterparty_name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('payment_method', sa.String(length=30), nullable=True))

    op.execute("""
        UPDATE transactions
        SET transaction_type = CASE transaction_type
            WHEN 'Debit' THEN 'DEBIT'
            WHEN 'Credit' THEN 'CREDIT'
            WHEN 'Expense' THEN 'EXPENSE'
            WHEN 'Revenue' THEN 'REVENUE'
            WHEN 'Payment' THEN 'PAYMENT'
            ELSE transaction_type
        END
    """)
    op.drop_constraint(
        'ck_transactions_payment_classification',
        'transactions',
        type_='check',
    )
    op.execute("""
        UPDATE transactions
        SET category = CASE category
            WHEN 'Milk Sale' THEN 'MILK_SALE'
            WHEN 'Milk Sales' THEN 'MILK_SALE'
            WHEN 'Livestock Sale' THEN 'LIVESTOCK_SALE'
            WHEN 'Livestock Sales' THEN 'LIVESTOCK_SALE'
            WHEN 'Other Income' THEN 'OTHER_INCOME'
            WHEN 'Payment' THEN 'PAYMENT'
            WHEN 'Inventory Write Off' THEN 'INVENTORY_WRITE_OFF'
            WHEN 'Other' THEN 'OTHER'
            WHEN 'Feed Purchase' THEN 'FEED_PURCHASE'
            WHEN 'Feed' THEN 'FEED_PURCHASE'
            WHEN 'Vet Fees' THEN 'VET_FEES'
            WHEN 'Vet Services' THEN 'VET_FEES'
            WHEN 'Labor' THEN 'LABOR_WAGES'
            WHEN 'Labor / Wages' THEN 'LABOR_WAGES'
            WHEN 'Utilities' THEN 'UTILITIES'
            WHEN 'Equipment Maintenance' THEN 'EQUIPMENT_MAINTENANCE'
            WHEN 'Transport' THEN 'TRANSPORT'
            WHEN 'Opening Balance' THEN 'OPENING_BALANCE'
            WHEN 'Buyer Payment' THEN 'BUYER_PAYMENT'
            ELSE category
        END
    """)
    op.execute("""
        UPDATE transactions
        SET transaction_type = 'PAYMENT'
        WHERE category IN ('PAYMENT', 'BUYER_PAYMENT')
    """)
    op.create_check_constraint(
        'ck_transactions_payment_classification',
        'transactions',
        "(transaction_type = 'PAYMENT') = (category IN ('PAYMENT', 'BUYER_PAYMENT'))",
    )
    op.execute('ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactioncategory')
    op.create_check_constraint(
        'transactioncategory',
        'transactions',
        "category IN ('MILK_SALE', 'LIVESTOCK_SALE', 'OTHER_INCOME', 'PAYMENT', "
        "'INVENTORY_WRITE_OFF', 'OTHER', 'FEED_PURCHASE', 'VET_FEES', "
        "'LABOR_WAGES', 'UTILITIES', 'EQUIPMENT_MAINTENANCE', 'TRANSPORT', "
        "'OPENING_BALANCE', 'BUYER_PAYMENT')",
    )


def downgrade():
    op.execute("UPDATE transactions SET category = 'OTHER' WHERE category IN ("
               "'LIVESTOCK_SALE', 'OTHER_INCOME', 'LABOR_WAGES', 'UTILITIES', "
               "'EQUIPMENT_MAINTENANCE', 'TRANSPORT', 'OPENING_BALANCE')")
    op.drop_constraint('transactioncategory', 'transactions', type_='check')
    op.create_check_constraint(
        'transactioncategory',
        'transactions',
        "category IN ('MILK_SALE', 'PAYMENT', 'INVENTORY_WRITE_OFF', 'OTHER', "
        "'FEED_PURCHASE', 'VET_FEES', 'BUYER_PAYMENT')",
    )
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_column('payment_method')
        batch_op.drop_column('counterparty_name')
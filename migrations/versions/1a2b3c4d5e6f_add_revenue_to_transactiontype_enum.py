"""Add REVENUE to TransactionType enum and standardize data.

Revision ID: 1a2b3c4d5e6f
Revises: 432fc760513f
Create Date: 2026-08-17 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1a2b3c4d5e6f'
down_revision = '432fc760513f'
branch_labels = None
depends_on = None


def upgrade():
    # Step 1: Standardize existing 'Revenue' data to 'REVENUE' to match the enum member case.
    op.execute("UPDATE transactions SET transaction_type = 'REVENUE' WHERE transaction_type = 'Revenue'")

    # Step 2: Drop the old CHECK constraint. The name 'transactiontype' comes from the
    # `name` parameter in the previous migration's sa.Enum(..., native_enum=False).
    op.drop_constraint('transactiontype', 'transactions', type_='check')

    # Step 3: Create a new CHECK constraint that includes the 'REVENUE' value.
    op.create_check_constraint(
        'transactiontype',
        'transactions',
        "transaction_type IN ('DEBIT', 'CREDIT', 'EXPENSE', 'REVENUE')"
    )


def downgrade():
    # To downgrade safely, we must first ensure no 'REVENUE' values exist.
    # We will convert them back to 'DEBIT' as a reasonable fallback.
    op.execute("UPDATE transactions SET transaction_type = 'DEBIT' WHERE transaction_type = 'REVENUE'")

    # Drop the new CHECK constraint.
    op.drop_constraint('transactiontype', 'transactions', type_='check')

    # Recreate the old CHECK constraint without 'REVENUE'.
    op.create_check_constraint(
        'transactiontype', 'transactions', "transaction_type IN ('DEBIT', 'CREDIT', 'EXPENSE')"
    )

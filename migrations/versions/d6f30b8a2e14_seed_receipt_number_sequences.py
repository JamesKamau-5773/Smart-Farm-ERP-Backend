"""seed receipt number sequences

Revision ID: d6f30b8a2e14
Revises: c2a91e7d4f08
"""

from alembic import op


revision = 'd6f30b8a2e14'
down_revision = 'c2a91e7d4f08'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO receipt_number_sequences (tenant_id, fiscal_year, next_number)
        SELECT
            tenant_id,
            SUBSTRING(receipt_number FROM '^RCPT-([0-9]{4})-')::integer AS fiscal_year,
            MAX(SUBSTRING(receipt_number FROM '([0-9]{6})$')::integer) + 1 AS next_number
        FROM receipts
        WHERE receipt_number ~ '^RCPT-[0-9]{4}-[0-9]{6}$'
        GROUP BY tenant_id, SUBSTRING(receipt_number FROM '^RCPT-([0-9]{4})-')::integer
        ON CONFLICT (tenant_id, fiscal_year)
        DO UPDATE SET next_number = GREATEST(
            receipt_number_sequences.next_number,
            EXCLUDED.next_number
        )
    """)


def downgrade():
    pass

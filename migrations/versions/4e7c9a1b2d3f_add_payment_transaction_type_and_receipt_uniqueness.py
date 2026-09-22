"""Add payment transaction type and receipt uniqueness

Revision ID: 4e7c9a1b2d3f
Revises: 2f1b3d6fcd02
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa


revision = '4e7c9a1b2d3f'
down_revision = '2f1b3d6fcd02'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        UPDATE deliveries AS delivery
        SET price_per_liter = customer.agreed_rate_per_liter,
            total_price = delivery.billable_liters * customer.agreed_rate_per_liter
        FROM customers AS customer
        WHERE delivery.customer_id = customer.id
          AND delivery.tenant_id = customer.tenant_id
          AND delivery.billable_liters > 0
          AND delivery.price_per_liter = 0
          AND customer.agreed_rate_per_liter > 0
    """))
    op.create_check_constraint(
        'ck_deliveries_billable_price_positive',
        'deliveries',
        'billable_liters = 0 OR price_per_liter > 0',
    )
    op.create_check_constraint(
        'ck_deliveries_total_matches_snapshot',
        'deliveries',
        'total_price = billable_liters * price_per_liter',
    )
    op.create_unique_constraint(
        'uq_transactions_tenant_reference_code',
        'transactions',
        ['tenant_id', 'reference_code'],
    )
    op.create_check_constraint(
        'ck_transactions_payment_classification',
        'transactions',
        "(transaction_type = 'PAYMENT') = (category IN ('PAYMENT', 'BUYER_PAYMENT'))",
    )


def downgrade():
    op.drop_constraint(
        'ck_transactions_payment_classification',
        'transactions',
        type_='check',
    )
    op.drop_constraint(
        'uq_transactions_tenant_reference_code',
        'transactions',
        type_='unique',
    )
    op.drop_constraint(
        'ck_deliveries_total_matches_snapshot',
        'deliveries',
        type_='check',
    )
    op.drop_constraint(
        'ck_deliveries_billable_price_positive',
        'deliveries',
        type_='check',
    )
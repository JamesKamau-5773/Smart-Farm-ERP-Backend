"""Backfill payroll ledger expenses

Revision ID: b6d8f0a2c4e5
Revises: a5c7e9f1b3d4
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa


revision = 'b6d8f0a2c4e5'
down_revision = 'a5c7e9f1b3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        UPDATE payroll_runs AS payroll_run
        SET farm_id = tenant_farm.farm_id
        FROM (
            SELECT tenant_id, MIN(id) AS farm_id
            FROM farms
            WHERE is_active IS TRUE
            GROUP BY tenant_id
            HAVING COUNT(*) = 1
        ) AS tenant_farm
        WHERE payroll_run.tenant_id = tenant_farm.tenant_id
          AND payroll_run.farm_id IS NULL
    """))
    op.execute(sa.text("""
        INSERT INTO transactions (
            tenant_id,
            farm_id,
            transaction_type,
            category,
            amount,
            item_name,
            cost_class,
            description,
            counterparty_name,
            timestamp,
            recorded_by,
            reference_code,
            status,
            posted_at,
            posted_by
        )
        SELECT
            payroll_run.tenant_id,
            payroll_run.farm_id,
            'EXPENSE',
            'LABOR_WAGES',
            payroll_run.total_net_pay,
            'Monthly payroll',
            'COGS',
            'Payroll for ' || payroll_run.payroll_year || '-' || LPAD(payroll_run.payroll_month::text, 2, '0'),
            'Employees',
            COALESCE(payroll_run.finalized_at, payroll_run.paid_at, payroll_run.generated_at),
            COALESCE(payroll_run.finalized_by, payroll_run.paid_by, payroll_run.generated_by),
            'PAYROLL-' || payroll_run.payroll_year || '-' || LPAD(payroll_run.payroll_month::text, 2, '0'),
            'POSTED',
            COALESCE(payroll_run.finalized_at, payroll_run.paid_at, payroll_run.generated_at),
            COALESCE(payroll_run.finalized_by, payroll_run.paid_by, payroll_run.generated_by)
        FROM payroll_runs AS payroll_run
        WHERE payroll_run.status IN ('Finalized', 'Paid')
          AND payroll_run.farm_id IS NOT NULL
          AND payroll_run.total_net_pay > 0
        ON CONFLICT ON CONSTRAINT uq_transactions_tenant_reference_code DO NOTHING
    """))


def downgrade():
    op.execute(sa.text("""
        DELETE FROM transactions
        WHERE reference_code LIKE 'PAYROLL-%'
          AND category = 'LABOR_WAGES'
    """))

"""Remove empty draft payroll runs

Revision ID: e3a5c7d9f1b2
Revises: b2d4f6a8c0e1
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa


revision = 'e3a5c7d9f1b2'
down_revision = 'b2d4f6a8c0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        DELETE FROM payroll_runs
        WHERE status = 'Draft'
          AND NOT EXISTS (
              SELECT 1
              FROM payroll_run_line_items
              WHERE payroll_run_line_items.payroll_run_id = payroll_runs.id
          )
    """))


def downgrade():
    pass

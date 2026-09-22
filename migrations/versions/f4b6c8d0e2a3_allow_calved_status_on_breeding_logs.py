"""Allow 'Calved' status on breeding_logs

Revision ID: f4b6c8d0e2a3
Revises: e8a4f2c9d7b1
Create Date: 2026-09-12
"""

from alembic import op


revision = 'f4b6c8d0e2a3'
down_revision = 'e8a4f2c9d7b1'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_breeding_logs_status_valid', 'breeding_logs', type_='check')
    op.create_check_constraint(
        'ck_breeding_logs_status_valid',
        'breeding_logs',
        "status IN ('Pending', 'Pregnant', 'Failed', 'Calved')",
    )


def downgrade():
    op.execute("UPDATE breeding_logs SET status = 'Failed' WHERE status = 'Calved'")
    op.drop_constraint('ck_breeding_logs_status_valid', 'breeding_logs', type_='check')
    op.create_check_constraint(
        'ck_breeding_logs_status_valid',
        'breeding_logs',
        "status IN ('Pending', 'Pregnant', 'Failed')",
    )

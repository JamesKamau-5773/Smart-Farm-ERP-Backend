"""add status to milk logs

Revision ID: f4a2c8d1e7b9
Revises: c6d4e8f1a2b3
Create Date: 2026-07-09 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'f4a2c8d1e7b9'
down_revision = 'c6d4e8f1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('milk_logs', sa.Column('status', sa.String(length=20), nullable=True))
    op.execute(
        """
        UPDATE milk_logs
        SET status = CASE
            WHEN verified_at IS NOT NULL THEN 'VERIFIED'
            WHEN anomaly_flag IS TRUE THEN 'FLAGGED'
            WHEN is_saleable IS FALSE THEN 'ISOLATED'
            ELSE 'RECORDED'
        END
        """
    )
    op.alter_column('milk_logs', 'status', nullable=False)
    op.create_check_constraint(
        'ck_milk_logs_status_valid',
        'milk_logs',
        "status IN ('RECORDED', 'ISOLATED', 'FLAGGED', 'VERIFIED')",
    )


def downgrade():
    op.drop_constraint('ck_milk_logs_status_valid', 'milk_logs', type_='check')
    op.drop_column('milk_logs', 'status')
"""Add farm ID to payroll runs

Revision ID: a5c7e9f1b3d4
Revises: f4b6d8e0a2c3
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa


revision = 'a5c7e9f1b3d4'
down_revision = 'f4b6d8e0a2c3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('payroll_runs', sa.Column('farm_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_payroll_runs_farm_id',
        'payroll_runs',
        'farms',
        ['farm_id'],
        ['id'],
    )
    op.create_index('ix_payroll_runs_farm_id', 'payroll_runs', ['farm_id'], unique=False)


def downgrade():
    op.drop_index('ix_payroll_runs_farm_id', table_name='payroll_runs')
    op.drop_constraint('fk_payroll_runs_farm_id', 'payroll_runs', type_='foreignkey')
    op.drop_column('payroll_runs', 'farm_id')

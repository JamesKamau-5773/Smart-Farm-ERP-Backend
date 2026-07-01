"""Add HR workflow fields to employees.

Revision ID: 3b7c9a2d8f1c
Revises: 6a7d2f1b9c4e
Create Date: 2026-07-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '3b7c9a2d8f1c'
down_revision = '6a7d2f1b9c4e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('employees', sa.Column('role', sa.String(length=50), nullable=True))
    op.add_column('employees', sa.Column('loan_balance', sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text('0')))
    op.add_column('employees', sa.Column('monthly_deduction', sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text('0')))
    op.add_column('employees', sa.Column('status', sa.String(length=20), nullable=False, server_default='ACTIVE'))
    op.add_column('employees', sa.Column('leave_type', sa.String(length=50), nullable=True))
    op.add_column('employees', sa.Column('leave_start_date', sa.Date(), nullable=True))
    op.add_column('employees', sa.Column('leave_end_date', sa.Date(), nullable=True))
    op.add_column('employees', sa.Column('expected_return_date', sa.Date(), nullable=True))
    op.add_column('employees', sa.Column('actual_return_date', sa.Date(), nullable=True))
    op.add_column('employees', sa.Column('unpaid_leave_days_this_month', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('employees', sa.Column('medical_certifications', sa.JSON(), nullable=True))
    op.add_column('employees', sa.Column('medical_notes', sa.Text(), nullable=True))
    op.add_column('employees', sa.Column('return_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('employees', sa.Column('return_verification_decision', sa.String(length=20), nullable=True))
    op.add_column('employees', sa.Column('return_verification_note', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('employees', 'return_verification_note')
    op.drop_column('employees', 'return_verification_decision')
    op.drop_column('employees', 'return_verified_at')
    op.drop_column('employees', 'medical_notes')
    op.drop_column('employees', 'medical_certifications')
    op.drop_column('employees', 'unpaid_leave_days_this_month')
    op.drop_column('employees', 'actual_return_date')
    op.drop_column('employees', 'expected_return_date')
    op.drop_column('employees', 'leave_end_date')
    op.drop_column('employees', 'leave_start_date')
    op.drop_column('employees', 'leave_type')
    op.drop_column('employees', 'status')
    op.drop_column('employees', 'monthly_deduction')
    op.drop_column('employees', 'loan_balance')
    op.drop_column('employees', 'role')
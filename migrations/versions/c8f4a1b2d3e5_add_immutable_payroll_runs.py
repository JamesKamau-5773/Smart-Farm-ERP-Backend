"""add immutable payroll runs

Revision ID: c8f4a1b2d3e5
Revises: f1d7c3a9be21
Create Date: 2026-08-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8f4a1b2d3e5'
down_revision = 'f1d7c3a9be21'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payroll_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('payroll_year', sa.Integer(), nullable=False),
        sa.Column('payroll_month', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Draft'),
        sa.Column('generated_by', sa.Integer(), nullable=True),
        sa.Column('finalized_by', sa.Integer(), nullable=True),
        sa.Column('paid_by', sa.Integer(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_gross_pay', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('total_net_pay', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('total_deductions', sa.Numeric(precision=14, scale=2), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'payroll_year', 'payroll_month', name='uq_payroll_runs_period'),
        sa.CheckConstraint("status IN ('Draft', 'Finalized', 'Paid', 'Cancelled')", name='ck_payroll_runs_status_valid'),
        sa.CheckConstraint('payroll_month >= 1 AND payroll_month <= 12', name='ck_payroll_runs_month_valid'),
    )
    op.create_index('ix_payroll_runs_tenant_id', 'payroll_runs', ['tenant_id'], unique=False)

    op.create_table(
        'payroll_run_line_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('payroll_run_id', sa.Integer(), nullable=False),
        sa.Column('staff_id', sa.Integer(), nullable=False),
        sa.Column('staff_name', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('base_salary', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('approved_leave_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('overdue_penalty_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('leave_deduction', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('overdue_penalty_deduction', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('advance_deduction', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('gross_pay', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('net_pay', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('loan_balance', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('monthly_deduction', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('leave_type', sa.String(length=50), nullable=True),
        sa.Column('leave_start_date', sa.Date(), nullable=True),
        sa.Column('leave_end_date', sa.Date(), nullable=True),
        sa.Column('expected_return_date', sa.Date(), nullable=True),
        sa.Column('actual_return_date', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['payroll_run_id'], ['payroll_runs.id']),
        sa.ForeignKeyConstraint(['staff_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('payroll_run_id', 'staff_id', name='uq_payroll_run_staff'),
    )
    op.create_index('ix_payroll_run_line_items_run_id', 'payroll_run_line_items', ['payroll_run_id'], unique=False)
    op.create_index('ix_payroll_run_line_items_staff_id', 'payroll_run_line_items', ['staff_id'], unique=False)


def downgrade():
    op.drop_index('ix_payroll_run_line_items_staff_id', table_name='payroll_run_line_items')
    op.drop_index('ix_payroll_run_line_items_run_id', table_name='payroll_run_line_items')
    op.drop_table('payroll_run_line_items')
    op.drop_index('ix_payroll_runs_tenant_id', table_name='payroll_runs')
    op.drop_table('payroll_runs')
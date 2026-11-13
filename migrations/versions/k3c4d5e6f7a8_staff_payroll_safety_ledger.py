"""staff offboarding, advance history, statutory payroll, milk holds and tests, ledger attachments

Revision ID: k3c4d5e6f7a8
Revises: j2b3c4d5e6f7
Create Date: 2026-11-03

Additive only: new nullable or defaulted columns and new tables. Existing
employees get statutory_deductions_enabled = true; existing payroll line items
get zero statutory amounts, which is what they were calculated with.
"""
from alembic import op
import sqlalchemy as sa


revision = 'k3c4d5e6f7a8'
down_revision = 'j2b3c4d5e6f7'
branch_labels = None
depends_on = None

_LINE_ITEM_AMOUNTS = (
    'taxable_pay', 'paye', 'nssf_employee', 'nssf_employer',
    'shif', 'housing_levy_employee', 'housing_levy_employer',
)


def upgrade():
    with op.batch_alter_table('employees') as batch:
        batch.add_column(sa.Column('statutory_deductions_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column('end_date', sa.Date(), nullable=True))
        batch.add_column(sa.Column('offboarding_reason', sa.String(30), nullable=True))
        batch.add_column(sa.Column('offboarding_note', sa.Text(), nullable=True))
        batch.add_column(sa.Column('offboarded_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('offboarded_by', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_employees_offboarded_by_users', 'users', ['offboarded_by'], ['id'], ondelete='SET NULL')
        batch.create_check_constraint(
            'ck_employees_offboarding_reason_valid',
            "offboarding_reason IS NULL OR offboarding_reason IN "
            "('RESIGNED', 'CONTRACT_ENDED', 'DISMISSED', 'REDUNDANCY', 'RETIRED', 'DECEASED', 'OTHER')",
        )

    with op.batch_alter_table('payroll_run_line_items') as batch:
        batch.add_column(sa.Column('days_paid', sa.Integer(), nullable=True))
        for column in _LINE_ITEM_AMOUNTS:
            batch.add_column(sa.Column(column, sa.Numeric(12, 2), nullable=False, server_default='0'))
        batch.add_column(sa.Column('statutory_rates_version', sa.String(20), nullable=True))

    op.create_table(
        'employee_loan_movements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=False, index=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('balance_after', sa.Numeric(12, 2), nullable=False),
        sa.Column('occurred_on', sa.Date(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('payroll_run_id', sa.Integer(), sa.ForeignKey('payroll_runs.id'), nullable=True, index=True),
        sa.Column('ledger_transaction_id', sa.Integer(), sa.ForeignKey('transactions.id'), nullable=True),
        sa.Column('recorded_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('ADVANCE', 'REPAYMENT', 'PAYROLL_DEDUCTION')", name='ck_employee_loan_movements_kind_valid'),
        sa.CheckConstraint('amount > 0', name='ck_employee_loan_movements_amount_positive'),
    )

    with op.batch_alter_table('cows') as batch:
        batch.add_column(sa.Column('hold_reason', sa.String(120), nullable=True))
        batch.add_column(sa.Column('hold_notes', sa.Text(), nullable=True))
        batch.add_column(sa.Column('hold_until', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('hold_set_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('hold_set_by', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_cows_hold_set_by_users', 'users', ['hold_set_by'], ['id'], ondelete='SET NULL')

    op.create_table(
        'milk_tests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('cow_id', sa.Integer(), sa.ForeignKey('cows.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('tested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('test_type', sa.String(60), nullable=False),
        sa.Column('result', sa.String(10), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('recorded_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("result IN ('PASS', 'FAIL')", name='ck_milk_tests_result_valid'),
    )
    op.create_index('ix_milk_tests_tenant_cow_tested_at', 'milk_tests', ['tenant_id', 'cow_id', 'tested_at'])

    op.create_table(
        'transaction_attachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transactions.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('stored_path', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(50), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('transaction_attachments')
    op.drop_index('ix_milk_tests_tenant_cow_tested_at', table_name='milk_tests')
    op.drop_table('milk_tests')
    with op.batch_alter_table('cows') as batch:
        batch.drop_constraint('fk_cows_hold_set_by_users', type_='foreignkey')
        for column in ('hold_set_by', 'hold_set_at', 'hold_until', 'hold_notes', 'hold_reason'):
            batch.drop_column(column)
    op.drop_table('employee_loan_movements')
    with op.batch_alter_table('payroll_run_line_items') as batch:
        batch.drop_column('statutory_rates_version')
        for column in reversed(_LINE_ITEM_AMOUNTS):
            batch.drop_column(column)
        batch.drop_column('days_paid')
    with op.batch_alter_table('employees') as batch:
        batch.drop_constraint('ck_employees_offboarding_reason_valid', type_='check')
        batch.drop_constraint('fk_employees_offboarded_by_users', type_='foreignkey')
        for column in ('offboarded_by', 'offboarded_at', 'offboarding_note', 'offboarding_reason', 'end_date', 'statutory_deductions_enabled'):
            batch.drop_column(column)

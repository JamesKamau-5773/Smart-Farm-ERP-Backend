"""Add employee registry and payroll tables

Revision ID: ea7d0c9f7b21
Revises: a8f6e2d1c4b0
Create Date: 2026-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ea7d0c9f7b21'
down_revision = 'a8f6e2d1c4b0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=120), nullable=False),
        sa.Column('id_number', sa.String(length=50), nullable=True),
        sa.Column('phone_number', sa.String(length=30), nullable=True),
        sa.Column('hire_date', sa.Date(), nullable=False),
        sa.Column('base_salary', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('contract_type', sa.String(length=30), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('id_card_doc_url', sa.String(length=255), nullable=True),
        sa.Column('contract_doc_url', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'id_number', name='uq_employees_tenant_id_number'),
    )
    op.create_index('ix_employees_tenant_id', 'employees', ['tenant_id'], unique=False)

    op.create_table(
        'payroll',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('staff_id', sa.Integer(), nullable=False),
        sa.Column('payroll_year', sa.Integer(), nullable=False),
        sa.Column('payroll_month', sa.Integer(), nullable=False),
        sa.Column('base_salary', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('bonuses', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'),
        sa.Column('deductions', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'),
        sa.Column('net_pay', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('Pending', 'Paid')", name='ck_payroll_status_valid'),
        sa.CheckConstraint('payroll_month >= 1 AND payroll_month <= 12', name='ck_payroll_month_valid'),
        sa.ForeignKeyConstraint(['staff_id'], ['employees.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'staff_id', 'payroll_year', 'payroll_month', name='uq_payroll_monthly_snapshot'),
    )
    op.create_index('ix_payroll_tenant_id', 'payroll', ['tenant_id'], unique=False)
    op.create_index('ix_payroll_staff_id', 'payroll', ['staff_id'], unique=False)


def downgrade():
    op.drop_index('ix_payroll_staff_id', table_name='payroll')
    op.drop_index('ix_payroll_tenant_id', table_name='payroll')
    op.drop_table('payroll')

    op.drop_index('ix_employees_tenant_id', table_name='employees')
    op.drop_table('employees')

"""add transaction correction audit

Revision ID: e8a4f2c9d7b1
Revises: c7d3e4f5a6b7
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa


revision = 'e8a4f2c9d7b1'
down_revision = 'c7d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('transactions', sa.Column('voided_by', sa.Integer(), nullable=True))
    op.add_column('transactions', sa.Column('void_reason', sa.String(length=255), nullable=True))
    op.add_column('transactions', sa.Column('corrected_from_transaction_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_transactions_voided_by', 'transactions', 'users', ['voided_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(
        'fk_transactions_corrected_from',
        'transactions',
        'transactions',
        ['corrected_from_transaction_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.create_index('ix_transactions_corrected_from_transaction_id', 'transactions', ['corrected_from_transaction_id'], unique=True)
    op.create_table(
        'transaction_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=30), nullable=False),
        sa.Column('performed_by', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['performed_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_transaction_audit_logs_tenant_id', 'transaction_audit_logs', ['tenant_id'])
    op.create_index('ix_transaction_audit_logs_transaction_id', 'transaction_audit_logs', ['transaction_id'])
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_transaction_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Transaction audit records are append-only';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER transaction_audit_logs_append_only
        BEFORE UPDATE OR DELETE ON transaction_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_transaction_audit_mutation();
    """)


def downgrade():
    op.execute('DROP TRIGGER IF EXISTS transaction_audit_logs_append_only ON transaction_audit_logs')
    op.execute('DROP FUNCTION IF EXISTS prevent_transaction_audit_mutation()')
    op.drop_index('ix_transaction_audit_logs_transaction_id', table_name='transaction_audit_logs')
    op.drop_index('ix_transaction_audit_logs_tenant_id', table_name='transaction_audit_logs')
    op.drop_table('transaction_audit_logs')
    op.drop_index('ix_transactions_corrected_from_transaction_id', table_name='transactions')
    op.drop_constraint('fk_transactions_corrected_from', 'transactions', type_='foreignkey')
    op.drop_constraint('fk_transactions_voided_by', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'corrected_from_transaction_id')
    op.drop_column('transactions', 'void_reason')
    op.drop_column('transactions', 'voided_by')
    op.drop_column('transactions', 'voided_at')
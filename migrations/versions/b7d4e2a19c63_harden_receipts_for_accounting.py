"""harden receipts for accounting

Revision ID: b7d4e2a19c63
Revises: a5f3c8d2e641
"""

from alembic import op
import sqlalchemy as sa


revision = 'b7d4e2a19c63'
down_revision = 'a5f3c8d2e641'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('farm_id', sa.Integer(), nullable=True))
    op.add_column('transactions', sa.Column('status', sa.String(length=20), nullable=False, server_default='POSTED'))
    op.add_column('transactions', sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('transactions', sa.Column('posted_by', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_transactions_farm_id', 'transactions', 'farms', ['farm_id'], ['id'])
    op.create_foreign_key('fk_transactions_posted_by', 'transactions', 'users', ['posted_by'], ['id'])
    op.create_index(op.f('ix_transactions_farm_id'), 'transactions', ['farm_id'])
    op.execute("UPDATE transactions SET posted_at = timestamp, posted_by = recorded_by WHERE status = 'POSTED'")

    op.add_column('receipts', sa.Column('farm_id', sa.Integer(), nullable=True))
    op.add_column('receipts', sa.Column('status', sa.String(length=20), nullable=False, server_default='ISSUED'))
    op.add_column('receipts', sa.Column('currency', sa.String(length=3), nullable=False, server_default='KES'))
    op.add_column('receipts', sa.Column('template_version', sa.String(length=20), nullable=False, server_default='1'))
    op.add_column('receipts', sa.Column('document_sha256', sa.String(length=64), nullable=True))
    op.add_column('receipts', sa.Column('document_content', sa.LargeBinary(), nullable=True))
    op.add_column('receipts', sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('receipts', sa.Column('voided_by', sa.Integer(), nullable=True))
    op.add_column('receipts', sa.Column('void_reason', sa.String(length=255), nullable=True))
    op.create_foreign_key('fk_receipts_farm_id', 'receipts', 'farms', ['farm_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key('fk_receipts_voided_by', 'receipts', 'users', ['voided_by'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_receipts_farm_id'), 'receipts', ['farm_id'])

    op.create_table(
        'receipt_number_sequences',
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('fiscal_year', sa.Integer(), nullable=False),
        sa.Column('next_number', sa.Integer(), nullable=False, server_default='1'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('tenant_id', 'fiscal_year'),
    )
    op.create_table(
        'receipt_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('receipt_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=30), nullable=False),
        sa.Column('performed_by', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['performed_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['receipt_id'], ['receipts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_receipt_audit_logs_receipt_id'), 'receipt_audit_logs', ['receipt_id'])
    op.create_index(op.f('ix_receipt_audit_logs_tenant_id'), 'receipt_audit_logs', ['tenant_id'])
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_receipt_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Issued receipts cannot be deleted';
            END IF;
            IF OLD.document_content IS NULL
               AND NEW.document_content IS NOT NULL
               AND NEW.document_sha256 IS NOT NULL
                AND NEW.tenant_id = OLD.tenant_id
                AND NEW.transaction_id = OLD.transaction_id
               AND NEW.snapshot = OLD.snapshot
               AND NEW.receipt_number = OLD.receipt_number
               AND NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'ISSUED'
               AND NEW.status = 'VOIDED'
               AND NEW.voided_at IS NOT NULL
               AND NEW.voided_by IS NOT NULL
               AND NULLIF(BTRIM(NEW.void_reason), '') IS NOT NULL
               AND NEW.snapshot = OLD.snapshot
               AND NEW.receipt_number = OLD.receipt_number
               AND NEW.tenant_id = OLD.tenant_id
               AND NEW.transaction_id = OLD.transaction_id
               AND NEW.farm_id IS NOT DISTINCT FROM OLD.farm_id
               AND NEW.currency = OLD.currency
               AND NEW.template_version = OLD.template_version
               AND NEW.document_content IS NOT DISTINCT FROM OLD.document_content
               AND NEW.document_sha256 IS NOT DISTINCT FROM OLD.document_sha256 THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Issued receipts are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER receipts_immutable
        BEFORE UPDATE OR DELETE ON receipts
        FOR EACH ROW EXECUTE FUNCTION prevent_receipt_mutation();
    """)
    op.execute("""
        CREATE FUNCTION prevent_receipt_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Receipt audit records are append-only';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER receipt_audit_logs_immutable
        BEFORE UPDATE OR DELETE ON receipt_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_receipt_audit_mutation();
    """)


def downgrade():
    op.execute('DROP TRIGGER IF EXISTS receipt_audit_logs_immutable ON receipt_audit_logs')
    op.execute('DROP FUNCTION IF EXISTS prevent_receipt_audit_mutation()')
    op.drop_table('receipt_audit_logs')
    op.drop_table('receipt_number_sequences')
    op.execute('DROP TRIGGER IF EXISTS receipts_immutable ON receipts')
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_receipt_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Issued receipts are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER receipts_immutable
        BEFORE UPDATE OR DELETE ON receipts
        FOR EACH ROW EXECUTE FUNCTION prevent_receipt_mutation();
    """)
    op.drop_index(op.f('ix_receipts_farm_id'), table_name='receipts')
    op.drop_constraint('fk_receipts_voided_by', 'receipts', type_='foreignkey')
    op.drop_constraint('fk_receipts_farm_id', 'receipts', type_='foreignkey')
    for column in ('void_reason', 'voided_by', 'voided_at', 'document_content', 'document_sha256', 'template_version', 'currency', 'status', 'farm_id'):
        op.drop_column('receipts', column)
    op.drop_index(op.f('ix_transactions_farm_id'), table_name='transactions')
    op.drop_constraint('fk_transactions_posted_by', 'transactions', type_='foreignkey')
    op.drop_constraint('fk_transactions_farm_id', 'transactions', type_='foreignkey')
    for column in ('posted_by', 'posted_at', 'status', 'farm_id'):
        op.drop_column('transactions', column)

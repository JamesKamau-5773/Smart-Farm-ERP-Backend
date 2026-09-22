"""add immutable transaction receipts

Revision ID: a5f3c8d2e641
Revises: 9e4f2a7b3c51
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a5f3c8d2e641'
down_revision = '9e4f2a7b3c51'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=False),
        sa.Column('receipt_number', sa.String(length=30), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('issued_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['issued_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transaction_id'),
        sa.UniqueConstraint('tenant_id', 'receipt_number', name='uq_receipts_tenant_number'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_receipts_tenant_id'),
    )
    op.create_index(op.f('ix_receipts_tenant_id'), 'receipts', ['tenant_id'], unique=False)
    op.execute("""
        CREATE FUNCTION prevent_receipt_mutation() RETURNS trigger AS $$
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


def downgrade():
    op.execute('DROP TRIGGER IF EXISTS receipts_immutable ON receipts')
    op.execute('DROP FUNCTION IF EXISTS prevent_receipt_mutation()')
    op.drop_index(op.f('ix_receipts_tenant_id'), table_name='receipts')
    op.drop_table('receipts')

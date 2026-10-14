"""Add source and CoA fields to finance transactions.

Revision ID: c1f2b3e4d5f6
Revises: 3c8e8b7a1d2a
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1f2b3e4d5f6'
down_revision = '3c8e8b7a1d2a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_document_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('source_document_type', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('source_cow_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('source_technician_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('chart_of_accounts_code', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('payment_status', sa.String(length=20), nullable=True))

        batch_op.create_index(batch_op.f('ix_transactions_source_document_id'), ['source_document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_source_document_type'), ['source_document_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_source_cow_id'), ['source_cow_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_source_technician_id'), ['source_technician_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_transactions_chart_of_accounts_code'), ['chart_of_accounts_code'], unique=False)

    op.execute("UPDATE transactions SET payment_status = 'UNPAID' WHERE payment_status IS NULL")

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('payment_status', nullable=False)
        batch_op.create_check_constraint(
            'ck_transactions_payment_status_valid',
            "payment_status IN ('UNPAID', 'PAYABLE', 'PARTIALLY_PAID', 'PAID')",
        )


def downgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_constraint('ck_transactions_payment_status_valid', type_='check')
        batch_op.drop_index(batch_op.f('ix_transactions_chart_of_accounts_code'))
        batch_op.drop_index(batch_op.f('ix_transactions_source_technician_id'))
        batch_op.drop_index(batch_op.f('ix_transactions_source_cow_id'))
        batch_op.drop_index(batch_op.f('ix_transactions_source_document_type'))
        batch_op.drop_index(batch_op.f('ix_transactions_source_document_id'))
        batch_op.drop_column('payment_status')
        batch_op.drop_column('chart_of_accounts_code')
        batch_op.drop_column('source_technician_id')
        batch_op.drop_column('source_cow_id')
        batch_op.drop_column('source_document_type')
        batch_op.drop_column('source_document_id')

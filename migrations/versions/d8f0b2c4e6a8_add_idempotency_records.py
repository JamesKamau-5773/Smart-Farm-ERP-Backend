"""Add tenant-scoped idempotency records.

Revision ID: d8f0b2c4e6a8
Revises: c7e9a1b3d5f7
Create Date: 2026-09-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'd8f0b2c4e6a8'
down_revision = 'c7e9a1b3d5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.String(length=64), nullable=False),
        sa.Column('idempotency_key', sa.String(length=200), nullable=False),
        sa.Column('request_method', sa.String(length=10), nullable=False),
        sa.Column('request_path', sa.String(length=500), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('response_mimetype', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED')",
            name='ck_idempotency_records_status',
        ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'tenant_id',
            'actor_id',
            'idempotency_key',
            name='uq_idempotency_records_scope_key',
        ),
    )
    op.create_index(
        op.f('ix_idempotency_records_tenant_id'),
        'idempotency_records',
        ['tenant_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_idempotency_records_tenant_id'), table_name='idempotency_records')
    op.drop_table('idempotency_records')
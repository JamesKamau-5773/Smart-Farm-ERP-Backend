"""Add milk dispositions

Revision ID: f4b6d8e0a2c3
Revises: e3a5c7d9f1b2
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa


revision = 'f4b6d8e0a2c3'
down_revision = 'e3a5c7d9f1b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'milk_dispositions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('disposition_type', sa.String(length=30), nullable=False),
        sa.Column('disposition_date', sa.Date(), nullable=False),
        sa.Column('liters', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('calf_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('recorded_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('liters > 0', name='ck_milk_dispositions_liters_positive'),
        sa.CheckConstraint("disposition_type IN ('CALF_FEED')", name='ck_milk_dispositions_type_valid'),
        sa.CheckConstraint(
            "disposition_type != 'CALF_FEED' OR calf_id IS NOT NULL",
            name='ck_milk_dispositions_calf_required',
        ),
        sa.ForeignKeyConstraint(['calf_id'], ['cows.id']),
        sa.ForeignKeyConstraint(['recorded_by'], ['users.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_milk_dispositions_tenant_id', 'milk_dispositions', ['tenant_id'], unique=False)
    op.create_index('ix_milk_dispositions_disposition_date', 'milk_dispositions', ['disposition_date'], unique=False)
    op.create_index('ix_milk_dispositions_calf_id', 'milk_dispositions', ['calf_id'], unique=False)


def downgrade():
    op.drop_index('ix_milk_dispositions_calf_id', table_name='milk_dispositions')
    op.drop_index('ix_milk_dispositions_disposition_date', table_name='milk_dispositions')
    op.drop_index('ix_milk_dispositions_tenant_id', table_name='milk_dispositions')
    op.drop_table('milk_dispositions')

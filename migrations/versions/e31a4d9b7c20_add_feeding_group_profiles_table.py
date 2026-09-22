"""add feeding group profiles table

Revision ID: e31a4d9b7c20
Revises: c7e2f1a9b3d5
Create Date: 2026-08-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e31a4d9b7c20'
down_revision = 'c7e2f1a9b3d5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'feeding_group_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('feeding_group', sa.String(length=40), nullable=False),
        sa.Column('avg_body_weight_kg', sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column('dmi_percent_bw', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('target_protein_percent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('feeding_times_per_day', sa.Integer(), nullable=False, server_default=sa.text('2')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'feeding_group', name='uq_feeding_group_profiles_tenant_group'),
        sa.CheckConstraint(
            "feeding_group IN ('lactating', 'dry', 'calf_0_3m', 'calf_3_6m', 'heifer')",
            name='ck_feeding_group_profiles_group_valid',
        ),
        sa.CheckConstraint('avg_body_weight_kg > 0', name='ck_feeding_group_profiles_body_weight_positive'),
        sa.CheckConstraint('dmi_percent_bw > 0 AND dmi_percent_bw <= 10', name='ck_feeding_group_profiles_dmi_range'),
        sa.CheckConstraint('target_protein_percent > 0 AND target_protein_percent <= 100', name='ck_feeding_group_profiles_protein_range'),
        sa.CheckConstraint('feeding_times_per_day > 0 AND feeding_times_per_day <= 12', name='ck_feeding_group_profiles_times_range'),
    )
    op.create_index(
        op.f('ix_feeding_group_profiles_tenant_id'),
        'feeding_group_profiles',
        ['tenant_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_feeding_group_profiles_tenant_id'), table_name='feeding_group_profiles')
    op.drop_table('feeding_group_profiles')

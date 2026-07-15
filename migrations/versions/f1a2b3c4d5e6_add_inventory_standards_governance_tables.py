"""add inventory standards governance tables

Revision ID: f1a2b3c4d5e6
Revises: e7b1c2d3f4a5
Create Date: 2026-07-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'e7b1c2d3f4a5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ingredient_standards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('canonical_name', sa.String(length=120), nullable=False),
        sa.Column('protein_grams_per_kg', sa.Numeric(10, 2), nullable=False),
        sa.Column('energy_mj_per_kg', sa.Numeric(10, 2), nullable=False),
        sa.Column('fiber_grams_per_kg', sa.Numeric(10, 2), nullable=False),
        sa.Column('cost_per_kg', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('source_reference', sa.String(length=255), nullable=True),
        sa.Column('standards_version', sa.String(length=40), nullable=False, server_default='2026.07'),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'canonical_name', 'standards_version', name='uq_ing_std_tenant_name_version'),
    )
    op.create_index('ix_ing_std_tenant_name', 'ingredient_standards', ['tenant_id', 'canonical_name'], unique=False)

    op.create_table(
        'ingredient_standard_synonyms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('standard_id', sa.Integer(), nullable=False),
        sa.Column('synonym', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['standard_id'], ['ingredient_standards.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('standard_id', 'synonym', name='uq_ing_std_synonym_per_standard'),
    )
    op.create_index('ix_ing_std_synonym_lookup', 'ingredient_standard_synonyms', ['synonym'], unique=False)

    op.create_table(
        'ingredient_category_baselines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=80), nullable=False),
        sa.Column('protein_grams_per_kg', sa.Numeric(10, 2), nullable=False),
        sa.Column('energy_mj_per_kg', sa.Numeric(10, 2), nullable=False),
        sa.Column('fiber_grams_per_kg', sa.Numeric(10, 2), nullable=False),
        sa.Column('cost_per_kg', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('source_reference', sa.String(length=255), nullable=True),
        sa.Column('standards_version', sa.String(length=40), nullable=False, server_default='2026.07'),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'category', 'standards_version', name='uq_ing_baseline_tenant_category_version'),
    )
    op.create_index('ix_ing_baseline_tenant_category', 'ingredient_category_baselines', ['tenant_id', 'category'], unique=False)

    op.create_table(
        'ingredient_standard_sync_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='PENDING'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('ingredient_standard_sync_jobs')
    op.drop_index('ix_ing_baseline_tenant_category', table_name='ingredient_category_baselines')
    op.drop_table('ingredient_category_baselines')
    op.drop_index('ix_ing_std_synonym_lookup', table_name='ingredient_standard_synonyms')
    op.drop_table('ingredient_standard_synonyms')
    op.drop_index('ix_ing_std_tenant_name', table_name='ingredient_standards')
    op.drop_table('ingredient_standards')

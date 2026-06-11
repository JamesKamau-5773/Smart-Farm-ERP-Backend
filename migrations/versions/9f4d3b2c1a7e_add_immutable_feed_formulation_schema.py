"""Add immutable feed formulation and batch cost snapshot schema.

Revision ID: 9f4d3b2c1a7e
Revises: 5e8c2b6f4d71
Create Date: 2026-06-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '9f4d3b2c1a7e'
down_revision = '2f3a9c5d7e11'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('current_cost_per_kg', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('stock_quantity', sa.Numeric(precision=14, scale=3), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_ingredients_tenant_name'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_ingredients_tenant_id'),
        sa.CheckConstraint('current_cost_per_kg >= 0', name='ck_ingredients_current_cost_non_negative'),
        sa.CheckConstraint('stock_quantity >= 0', name='ck_ingredients_stock_quantity_non_negative'),
    )

    op.create_table(
        'feed_formulas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_feed_formulas_tenant_name'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_feed_formulas_tenant_id'),
    )

    op.create_table(
        'formula_ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('formula_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('default_weight', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'formula_id'],
            ['feed_formulas.tenant_id', 'feed_formulas.id'],
            ondelete='CASCADE',
            name='fk_formula_ingredients_formula_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'ingredient_id'],
            ['ingredients.tenant_id', 'ingredients.id'],
            ondelete='RESTRICT',
            name='fk_formula_ingredients_ingredient_tenant',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'formula_id', 'ingredient_id', name='uq_formula_ingredients_formula_ingredient'),
        sa.CheckConstraint('default_weight > 0', name='ck_formula_ingredients_default_weight_positive'),
    )

    op.create_table(
        'feed_batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('formula_id', sa.Integer(), nullable=True),
        sa.Column('batch_name', sa.String(length=255), nullable=False),
        sa.Column('total_weight', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('total_cost', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('cost_per_kg', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column('mixed_on', sa.Date(), nullable=False, server_default=sa.text('CURRENT_DATE')),
        sa.Column('depleted_on', sa.Date(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'formula_id'],
            ['feed_formulas.tenant_id', 'feed_formulas.id'],
            ondelete='RESTRICT',
            name='fk_feed_batches_formula_tenant',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_feed_batches_tenant_id'),
        sa.CheckConstraint("status IN ('ACTIVE', 'DEPLETED', 'VOIDED')", name='ck_feed_batches_status_valid'),
        sa.CheckConstraint('total_weight > 0', name='ck_feed_batches_total_weight_positive'),
        sa.CheckConstraint('total_cost >= 0', name='ck_feed_batches_total_cost_non_negative'),
        sa.CheckConstraint('cost_per_kg >= 0', name='ck_feed_batches_cost_per_kg_non_negative'),
        sa.CheckConstraint('depleted_on IS NULL OR depleted_on >= mixed_on', name='ck_feed_batches_depleted_after_mixed'),
    )

    op.create_table(
        'batch_ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('percentage', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('locked_cost_per_kg', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'batch_id'],
            ['feed_batches.tenant_id', 'feed_batches.id'],
            ondelete='CASCADE',
            name='fk_batch_ingredients_batch_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'ingredient_id'],
            ['ingredients.tenant_id', 'ingredients.id'],
            ondelete='RESTRICT',
            name='fk_batch_ingredients_ingredient_tenant',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'batch_id', 'ingredient_id', name='uq_batch_ingredients_batch_ingredient'),
        sa.CheckConstraint('weight > 0', name='ck_batch_ingredients_weight_positive'),
        sa.CheckConstraint('percentage > 0 AND percentage <= 100', name='ck_batch_ingredients_percentage_range'),
        sa.CheckConstraint('locked_cost_per_kg >= 0', name='ck_batch_ingredients_locked_cost_non_negative'),
    )

    op.create_index('ix_ingredients_tenant_id', 'ingredients', ['tenant_id'], unique=False)
    op.create_index('ix_ingredients_tenant_name', 'ingredients', ['tenant_id', 'name'], unique=False)
    op.create_index('ix_feed_formulas_tenant_id', 'feed_formulas', ['tenant_id'], unique=False)
    op.create_index('ix_feed_formulas_tenant_created_at', 'feed_formulas', ['tenant_id', 'created_at'], unique=False)
    op.create_index('ix_formula_ingredients_tenant_id', 'formula_ingredients', ['tenant_id'], unique=False)
    op.create_index('ix_formula_ingredients_formula_id', 'formula_ingredients', ['formula_id'], unique=False)
    op.create_index('ix_formula_ingredients_ingredient_id', 'formula_ingredients', ['ingredient_id'], unique=False)
    op.create_index('ix_formula_ingredients_tenant_formula', 'formula_ingredients', ['tenant_id', 'formula_id'], unique=False)
    op.create_index('ix_feed_batches_tenant_id', 'feed_batches', ['tenant_id'], unique=False)
    op.create_index('ix_feed_batches_formula_id', 'feed_batches', ['formula_id'], unique=False)
    op.create_index('ix_feed_batches_tenant_status_mixed_on', 'feed_batches', ['tenant_id', 'status', 'mixed_on'], unique=False)
    op.create_index('ix_batch_ingredients_tenant_id', 'batch_ingredients', ['tenant_id'], unique=False)
    op.create_index('ix_batch_ingredients_batch_id', 'batch_ingredients', ['batch_id'], unique=False)
    op.create_index('ix_batch_ingredients_ingredient_id', 'batch_ingredients', ['ingredient_id'], unique=False)


def downgrade():
    op.drop_index('ix_batch_ingredients_ingredient_id', table_name='batch_ingredients')
    op.drop_index('ix_batch_ingredients_batch_id', table_name='batch_ingredients')
    op.drop_index('ix_batch_ingredients_tenant_id', table_name='batch_ingredients')
    op.drop_index('ix_feed_batches_tenant_status_mixed_on', table_name='feed_batches')
    op.drop_index('ix_feed_batches_formula_id', table_name='feed_batches')
    op.drop_index('ix_feed_batches_tenant_id', table_name='feed_batches')
    op.drop_index('ix_formula_ingredients_tenant_formula', table_name='formula_ingredients')
    op.drop_index('ix_formula_ingredients_ingredient_id', table_name='formula_ingredients')
    op.drop_index('ix_formula_ingredients_formula_id', table_name='formula_ingredients')
    op.drop_index('ix_formula_ingredients_tenant_id', table_name='formula_ingredients')
    op.drop_index('ix_feed_formulas_tenant_created_at', table_name='feed_formulas')
    op.drop_index('ix_feed_formulas_tenant_id', table_name='feed_formulas')
    op.drop_index('ix_ingredients_tenant_name', table_name='ingredients')
    op.drop_index('ix_ingredients_tenant_id', table_name='ingredients')

    op.drop_table('batch_ingredients')
    op.drop_table('feed_batches')
    op.drop_table('formula_ingredients')
    op.drop_table('feed_formulas')
    op.drop_table('ingredients')

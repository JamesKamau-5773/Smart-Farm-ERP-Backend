"""Add inventory batches, recipes, measurement units, and herd planning tables.

Revision ID: d4f6c1a8b2e7
Revises: 8c2b4f9d1e40
Create Date: 2026-05-28 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd4f6c1a8b2e7'
down_revision = '8c2b4f9d1e40'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'inventory_items',
        sa.Column('energy_mj_per_kg', sa.Numeric(precision=5, scale=2), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'inventory_items',
        sa.Column('protein_grams_per_kg', sa.Numeric(precision=5, scale=2), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'inventory_items',
        sa.Column('fiber_grams_per_kg', sa.Numeric(precision=5, scale=2), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'inventory_items',
        sa.Column('cost_per_kg', sa.Numeric(precision=10, scale=2), nullable=False, server_default=sa.text('0')),
    )

    op.add_column(
        'inventory_transactions',
        sa.Column('unit_cost', sa.Numeric(precision=10, scale=2), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'inventory_transactions',
        sa.Column('inventory_batch_id', sa.Integer(), nullable=True),
    )
    op.execute(
        'ALTER TABLE inventory_transactions '
        'ADD COLUMN total_transaction_value NUMERIC(12,2) '
        'GENERATED ALWAYS AS (quantity * unit_cost) STORED'
    )

    op.create_table(
        'inventory_batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('supplier_name', sa.String(length=100), nullable=False),
        sa.Column('received_quantity_kg', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_per_kg', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('quality_rating', sa.String(length=20), nullable=True),
        sa.Column('actual_protein_percentage', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('received_date', sa.Date(), nullable=False, server_default=sa.text('CURRENT_DATE')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ondelete='RESTRICT'),
        sa.CheckConstraint("quality_rating IN ('Excellent', 'Standard', 'Poor')", name='ck_inventory_batches_quality_rating_valid'),
        sa.UniqueConstraint('tenant_id', 'item_id', 'supplier_name', 'received_date', name='uq_tenant_item_supplier_date'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_foreign_key(
        'fk_inv_batch',
        'inventory_transactions',
        'inventory_batches',
        ['inventory_batch_id'],
        ['id'],
        ondelete='RESTRICT',
    )

    op.create_table(
        'expense_ledger',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('expense_date', sa.Date(), nullable=False, server_default=sa.text('CURRENT_DATE')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'feed_recipes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('recipe_name', sa.String(length=100), nullable=False),
        sa.Column('target_protein_percentage', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'recipe_ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('recipe_id', sa.Integer(), nullable=False),
        sa.Column('inventory_item_id', sa.Integer(), nullable=False),
        sa.Column('inclusion_percentage', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipe_id'], ['feed_recipes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['inventory_item_id'], ['inventory_items.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('recipe_id', 'inventory_item_id', name='uq_recipe_ingredient'),
    )

    op.create_table(
        'farm_measurement_units',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('unit_name', sa.String(length=50), nullable=False),
        sa.Column('kg_equivalent', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'item_id', 'unit_name', name='uq_tenant_item_unit'),
    )

    op.create_table(
        'animal_yield_targets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('animal_id', sa.Integer(), nullable=False),
        sa.Column('target_liters', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('times_to_feed_daily', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('base_herd_feed_kg', sa.Numeric(precision=5, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('milking_topup_kg', sa.Numeric(precision=5, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'Active'")),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['animal_id'], ['cows.id'], ondelete='CASCADE'),
        sa.CheckConstraint('times_to_feed_daily IN (2, 3, 4)', name='ck_animal_yield_targets_times_to_feed_daily_valid'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'herdsman_routine_template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('task_title', sa.String(length=100), nullable=False),
        sa.Column('task_description', sa.Text(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'daily_task_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('routine_id', sa.Integer(), nullable=False),
        sa.Column('herdsman_id', sa.Integer(), nullable=False),
        sa.Column('issue_tag', sa.String(length=100), nullable=False, server_default=sa.text("'None'")),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['routine_id'], ['herdsman_routine_template.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['herdsman_id'], ['users.id'], ondelete='RESTRICT'),
        sa.CheckConstraint("status IN ('Completed', 'Deviated')", name='ck_daily_task_logs_status_valid'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('idx_inv_batches_tenant', 'inventory_batches', ['tenant_id'], unique=False)
    op.create_index('idx_inv_batches_item_id', 'inventory_batches', ['item_id'], unique=False)
    op.create_index('idx_recipe_ing_tenant', 'recipe_ingredients', ['tenant_id'], unique=False)
    op.create_index('idx_recipe_ing_recipe_id', 'recipe_ingredients', ['recipe_id'], unique=False)
    op.create_index('idx_recipe_ing_item_id', 'recipe_ingredients', ['inventory_item_id'], unique=False)
    op.create_index('idx_expense_ledger_tenant', 'expense_ledger', ['tenant_id'], unique=False)
    op.create_index('idx_recipes_tenant', 'feed_recipes', ['tenant_id'], unique=False)
    op.create_index('idx_farm_units_tenant', 'farm_measurement_units', ['tenant_id'], unique=False)
    op.create_index('idx_farm_units_item_id', 'farm_measurement_units', ['item_id'], unique=False)
    op.create_index('idx_targets_tenant', 'animal_yield_targets', ['tenant_id'], unique=False)
    op.create_index('idx_targets_animal_id', 'animal_yield_targets', ['animal_id'], unique=False)
    op.create_index('idx_tasks_tenant', 'daily_task_logs', ['tenant_id'], unique=False)
    op.create_index('idx_tasks_routine_id', 'daily_task_logs', ['routine_id'], unique=False)
    op.create_index('idx_tasks_herdsman_id', 'daily_task_logs', ['herdsman_id'], unique=False)

    op.create_index('idx_inv_trans_batch_id', 'inventory_transactions', ['inventory_batch_id'], unique=False)
    op.create_index('idx_inv_trans_item_id', 'inventory_transactions', ['item_id'], unique=False)


def downgrade():
    op.drop_index('idx_inv_trans_item_id', table_name='inventory_transactions')
    op.drop_index('idx_inv_trans_batch_id', table_name='inventory_transactions')
    op.drop_index('idx_tasks_herdsman_id', table_name='daily_task_logs')
    op.drop_index('idx_tasks_routine_id', table_name='daily_task_logs')
    op.drop_index('idx_tasks_tenant', table_name='daily_task_logs')
    op.drop_index('idx_targets_animal_id', table_name='animal_yield_targets')
    op.drop_index('idx_targets_tenant', table_name='animal_yield_targets')
    op.drop_index('idx_farm_units_item_id', table_name='farm_measurement_units')
    op.drop_index('idx_farm_units_tenant', table_name='farm_measurement_units')
    op.drop_index('idx_recipes_tenant', table_name='feed_recipes')
    op.drop_index('idx_expense_ledger_tenant', table_name='expense_ledger')
    op.drop_index('idx_recipe_ing_item_id', table_name='recipe_ingredients')
    op.drop_index('idx_recipe_ing_recipe_id', table_name='recipe_ingredients')
    op.drop_index('idx_recipe_ing_tenant', table_name='recipe_ingredients')
    op.drop_index('idx_inv_batches_item_id', table_name='inventory_batches')
    op.drop_index('idx_inv_batches_tenant', table_name='inventory_batches')

    op.drop_table('daily_task_logs')
    op.drop_table('herdsman_routine_template')
    op.drop_table('animal_yield_targets')
    op.drop_table('farm_measurement_units')
    op.drop_table('recipe_ingredients')
    op.drop_table('feed_recipes')
    op.drop_table('expense_ledger')

    op.drop_constraint('fk_inv_batch', 'inventory_transactions', type_='foreignkey')
    op.execute('ALTER TABLE inventory_transactions DROP COLUMN total_transaction_value')
    op.drop_column('inventory_transactions', 'inventory_batch_id')
    op.drop_column('inventory_transactions', 'unit_cost')

    op.drop_table('inventory_batches')

    op.drop_column('inventory_items', 'cost_per_kg')
    op.drop_column('inventory_items', 'fiber_grams_per_kg')
    op.drop_column('inventory_items', 'protein_grams_per_kg')
    op.drop_column('inventory_items', 'energy_mj_per_kg')
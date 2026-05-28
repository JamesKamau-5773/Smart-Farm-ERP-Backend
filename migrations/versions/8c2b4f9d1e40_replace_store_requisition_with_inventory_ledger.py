"""Replace store requisition tables with inventory master/ledger

Revision ID: 8c2b4f9d1e40
Revises: 390d029aa1ce
Create Date: 2026-05-26 00:00:00.000000
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = '8c2b4f9d1e40'
down_revision = '390d029aa1ce'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    return sa.inspect(conn).has_table(table_name)


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
            """
        ),
        {"table": table_name, "column": column_name},
    ).scalar()
    return result is not None


def _get_default_tenant_id(conn) -> int:
    tenant_id = conn.execute(sa.text('SELECT id FROM tenants ORDER BY id LIMIT 1')).scalar()
    if tenant_id is None:
        raise RuntimeError('Cannot migrate inventory_items without at least one tenant row.')
    return tenant_id


def upgrade():
    conn = op.get_bind()
    default_tenant_id = _get_default_tenant_id(conn) if _table_exists(conn, 'tenants') else None

    op.create_table(
        'inventory_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('current_qty', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('minimum_threshold', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_inventory_items_tenant_name'),
    )
    op.create_index(op.f('ix_inventory_items_tenant_id'), 'inventory_items', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_inventory_items_name'), 'inventory_items', ['name'], unique=False)

    op.create_table(
        'inventory_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('transaction_type', sa.String(length=10), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('reference_note', sa.Text(), nullable=True),
        sa.Column('logged_by', sa.Integer(), nullable=True),
        sa.Column('transaction_date', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id']),
        sa.ForeignKeyConstraint(['logged_by'], ['users.id']),
        sa.CheckConstraint("transaction_type IN ('IN', 'OUT')", name='ck_inventory_transactions_type_valid'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_inventory_transactions_item_id'), 'inventory_transactions', ['item_id'], unique=False)
    op.create_index(op.f('ix_inventory_transactions_transaction_date'), 'inventory_transactions', ['transaction_date'], unique=False)

    item_map = {}
    if _table_exists(conn, 'store_items'):
        has_tenant_id = _column_exists(conn, 'store_items', 'tenant_id')
        if has_tenant_id:
            old_items = conn.execute(
                sa.text(
                    "SELECT id, tenant_id, name, category, unit_of_measure, current_stock, min_threshold FROM store_items"
                )
            ).mappings().all()
        else:
            old_items = conn.execute(
                sa.text(
                    "SELECT id, name, category, unit_of_measure, current_stock, min_threshold FROM store_items"
                )
            ).mappings().all()

        if not has_tenant_id and default_tenant_id is None:
            raise RuntimeError('Cannot infer tenant_id for legacy store_items rows.')

        for row in old_items:
            new_id = row['id']
            item_map[row['id']] = new_id
            conn.execute(
                sa.text(
                    """
                    INSERT INTO inventory_items (id, tenant_id, name, category, unit, current_qty, minimum_threshold, created_at)
                    VALUES (:id, :tenant_id, :name, :category, :unit, :current_qty, :minimum_threshold, :created_at)
                    """
                ),
                {
                    'id': new_id,
                    'tenant_id': row['tenant_id'] if has_tenant_id else default_tenant_id,
                    'name': row['name'],
                    'category': row['category'],
                    'unit': row['unit_of_measure'],
                    'current_qty': row['current_stock'],
                    'minimum_threshold': row['min_threshold'],
                    'created_at': datetime.utcnow(),
                },
            )

    if _table_exists(conn, 'feed_requisitions'):
        old_transactions = conn.execute(
            sa.text(
                "SELECT id, item_id, amount_used, timestamp, recorded_by, notes FROM feed_requisitions"
            )
        ).mappings().all()
        for row in old_transactions:
            mapped_item_id = item_map.get(row['item_id'])
            if not mapped_item_id:
                continue
            conn.execute(
                sa.text(
                    """
                    INSERT INTO inventory_transactions (id, item_id, transaction_type, quantity, reference_note, logged_by, transaction_date)
                    VALUES (:id, :item_id, 'OUT', :quantity, :reference_note, :logged_by, :transaction_date)
                    """
                ),
                {
                    'id': row['id'],
                    'item_id': mapped_item_id,
                    'quantity': row['amount_used'],
                    'reference_note': row['notes'],
                    'logged_by': row['recorded_by'],
                    'transaction_date': row['timestamp'],
                },
            )

    if _table_exists(conn, 'feed_requisitions'):
        op.drop_table('feed_requisitions')
    if _table_exists(conn, 'store_items'):
        op.drop_table('store_items')


def downgrade():
    op.create_table(
        'store_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('unit_of_measure', sa.String(length=20), nullable=False),
        sa.Column('current_stock', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('min_threshold', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('unit_cost', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_store_items_name'), 'store_items', ['name'], unique=True)

    op.create_table(
        'feed_requisitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('amount_used', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('recorded_by', sa.Integer(), nullable=False),
        sa.Column('target_cow_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['store_items.id']),
        sa.ForeignKeyConstraint(['recorded_by'], ['users.id']),
        sa.ForeignKeyConstraint(['target_cow_id'], ['cows.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_feed_requisitions_timestamp'), 'feed_requisitions', ['timestamp'], unique=False)

    op.drop_index(op.f('ix_inventory_transactions_transaction_date'), table_name='inventory_transactions')
    op.drop_index(op.f('ix_inventory_transactions_item_id'), table_name='inventory_transactions')
    op.drop_table('inventory_transactions')

    op.drop_index(op.f('ix_inventory_items_name'), table_name='inventory_items')
    op.drop_index(op.f('ix_inventory_items_tenant_id'), table_name='inventory_items')
    op.drop_table('inventory_items')

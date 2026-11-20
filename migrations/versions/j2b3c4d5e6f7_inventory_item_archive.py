"""Inventory: archive flag on items.

Archived items keep their recipes, batches and stock history but are hidden
from inventory lists and cannot be added to new feed mixes.

Revision ID: j2b3c4d5e6f7
Revises: i1a2b3c4d5e6
Create Date: 2026-11-03 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'j2b3c4d5e6f7'
down_revision = 'i1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_items', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column('inventory_items', 'is_active')

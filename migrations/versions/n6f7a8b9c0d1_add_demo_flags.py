"""Flag the public demo workspace and its accounts.

Revision ID: n6f7a8b9c0d1
Revises: m5e6f7a8b9c0
Create Date: 2026-11-13

* ``tenants.is_demo`` marks the read-only demo workspace ("Silato Farm").
* ``users.is_demo`` marks its accounts, which cannot sign in through the normal routes.
"""
from alembic import op
import sqlalchemy as sa


revision = 'n6f7a8b9c0d1'
down_revision = 'm5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tenants', sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.false()))
    # At most one demo workspace.
    op.create_index(
        'uq_tenants_single_demo', 'tenants', ['is_demo'], unique=True,
        postgresql_where=sa.text('is_demo'),
    )


def downgrade():
    op.drop_index('uq_tenants_single_demo', table_name='tenants')
    op.drop_column('users', 'is_demo')
    op.drop_column('tenants', 'is_demo')

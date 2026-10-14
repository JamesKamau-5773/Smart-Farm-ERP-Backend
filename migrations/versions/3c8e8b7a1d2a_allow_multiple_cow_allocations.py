"""Allow one expense to allocate to multiple cows.

Revision ID: 3c8e8b7a1d2a
Revises: 9c2e4f6a8b1d
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3c8e8b7a1d2a'
down_revision = '9c2e4f6a8b1d'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    has_constraint = bind.execute(sa.text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'animal_cost_allocations'::regclass
              AND conname = 'animal_cost_allocations_transaction_id_key'
        )
        """
    )).scalar()
    if has_constraint:
        with op.batch_alter_table('animal_cost_allocations', schema=None) as batch_op:
            batch_op.drop_constraint('animal_cost_allocations_transaction_id_key', type_='unique')


def downgrade():
    bind = op.get_bind()
    has_constraint = bind.execute(sa.text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'animal_cost_allocations'::regclass
              AND conname = 'animal_cost_allocations_transaction_id_key'
        )
        """
    )).scalar()
    if not has_constraint:
        with op.batch_alter_table('animal_cost_allocations', schema=None) as batch_op:
            batch_op.create_unique_constraint('animal_cost_allocations_transaction_id_key', ['transaction_id'])

"""add recipe_id to feed_batches for direct planner-recipe attribution

Adds a nullable recipe_id to feed_batches pointing at feed_recipes so a batch
created from a planner mix is attributed to that recipe exactly, instead of
relying on ingredient-signature inference. Nullable keeps existing batches
untouched (they keep recipe_id NULL and fall back to signature matching).

Revision ID: c7e2f1a9b3d5
Revises: fb98d97abdfd
Create Date: 2026-08-24

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e2f1a9b3d5'
down_revision = 'fb98d97abdfd'
branch_labels = None
depends_on = None


def upgrade():
    # Tenant-safe target for the composite FK below.
    op.create_unique_constraint(
        'uq_feed_recipes_tenant_id', 'feed_recipes', ['tenant_id', 'id']
    )
    with op.batch_alter_table('feed_batches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recipe_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_feed_batches_recipe_tenant',
            'feed_recipes',
            ['tenant_id', 'recipe_id'],
            ['tenant_id', 'id'],
            ondelete='SET NULL',
        )
        batch_op.create_index(
            'ix_feed_batches_tenant_recipe', ['tenant_id', 'recipe_id']
        )


def downgrade():
    with op.batch_alter_table('feed_batches', schema=None) as batch_op:
        batch_op.drop_index('ix_feed_batches_tenant_recipe')
        batch_op.drop_constraint('fk_feed_batches_recipe_tenant', type_='foreignkey')
        batch_op.drop_column('recipe_id')
    op.drop_constraint('uq_feed_recipes_tenant_id', 'feed_recipes', type_='unique')

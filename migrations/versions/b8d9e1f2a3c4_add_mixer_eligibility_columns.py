"""add mixer eligibility columns

Revision ID: b8d9e1f2a3c4
Revises: 1a2b3c4d5e7f
Create Date: 2026-07-15 18:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8d9e1f2a3c4'
down_revision = '1a2b3c4d5e7f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('inventory_items', sa.Column('allowed_mixers', sa.String(length=120), nullable=True))
    op.add_column('inventory_items', sa.Column('mixer_role', sa.String(length=50), nullable=True))
    op.add_column('inventory_items', sa.Column('inclusion_percentage_dairy_meal', sa.Numeric(5, 2), nullable=False, server_default='0'))
    op.add_column('inventory_items', sa.Column('inclusion_percentage_main_meal', sa.Numeric(5, 2), nullable=False, server_default='0'))

    op.add_column('feed_recipes', sa.Column('recipe_type', sa.String(length=40), nullable=True))
    op.add_column('feed_recipes', sa.Column('created_by', sa.Integer(), nullable=True))

    op.execute("UPDATE feed_recipes SET recipe_type = 'main_meal' WHERE recipe_type IS NULL")
    op.alter_column('feed_recipes', 'recipe_type', existing_type=sa.String(length=40), nullable=False)

    op.create_check_constraint(
        'ck_feed_recipes_recipe_type_valid',
        'feed_recipes',
        "recipe_type IN ('dairy_meal', 'main_meal')",
    )
    op.create_foreign_key(
        'fk_feed_recipes_created_by_users',
        'feed_recipes',
        'users',
        ['created_by'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_feed_recipes_created_by_users', 'feed_recipes', type_='foreignkey')
    op.drop_constraint('ck_feed_recipes_recipe_type_valid', 'feed_recipes', type_='check')

    op.drop_column('feed_recipes', 'created_by')
    op.drop_column('feed_recipes', 'recipe_type')

    op.drop_column('inventory_items', 'inclusion_percentage_main_meal')
    op.drop_column('inventory_items', 'inclusion_percentage_dairy_meal')
    op.drop_column('inventory_items', 'mixer_role')
    op.drop_column('inventory_items', 'allowed_mixers')

"""classify existing dairy meal recipes

Revision ID: 9e4f2a7b3c51
Revises: 8d3e1f6a2b40
"""

from alembic import op


revision = '9e4f2a7b3c51'
down_revision = '8d3e1f6a2b40'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE feed_recipes SET quantity_basis = 'concentrate' "
        "WHERE recipe_type = 'dairy_meal'"
    )


def downgrade():
    op.execute(
        "UPDATE feed_recipes SET quantity_basis = 'total_ration' "
        "WHERE recipe_type = 'dairy_meal'"
    )

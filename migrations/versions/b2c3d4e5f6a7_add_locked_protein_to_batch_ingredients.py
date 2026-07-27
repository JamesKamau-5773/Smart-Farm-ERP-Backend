"""add locked_protein_grams_per_kg to batch_ingredients

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-17 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Add protein snapshot column. Default 0 so existing rows remain valid;
    # historical batches will show 0% until ingredients are updated and
    # new batches are mixed.
    op.add_column(
        'batch_ingredients',
        sa.Column(
            'locked_protein_grams_per_kg',
            sa.Numeric(precision=7, scale=2),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )


def downgrade():
    op.drop_column('batch_ingredients', 'locked_protein_grams_per_kg')

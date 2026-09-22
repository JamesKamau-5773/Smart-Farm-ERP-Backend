"""add feed recipe measurement calibration

Revision ID: 8d3e1f6a2b40
Revises: 7c2d9e4a1f60
"""

from alembic import op
import sqlalchemy as sa


revision = '8d3e1f6a2b40'
down_revision = '7c2d9e4a1f60'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('feed_recipes') as batch_op:
        batch_op.add_column(sa.Column('quantity_basis', sa.String(length=30), nullable=False, server_default='total_ration'))
        batch_op.add_column(sa.Column('concentrate_kg_per_head_day', sa.Numeric(precision=7, scale=3), nullable=True))
        batch_op.add_column(sa.Column('bulk_density_kg_per_litre', sa.Numeric(precision=7, scale=4), nullable=True))
        batch_op.add_column(sa.Column('bucket_volume_litres', sa.Numeric(precision=7, scale=3), nullable=True))
        batch_op.add_column(sa.Column('scoop_weight_kg', sa.Numeric(precision=7, scale=3), nullable=True))
        batch_op.create_check_constraint('ck_feed_recipes_quantity_basis_valid', "quantity_basis IN ('total_ration', 'concentrate')")
        batch_op.create_check_constraint('ck_feed_recipes_concentrate_rate_positive', 'concentrate_kg_per_head_day IS NULL OR concentrate_kg_per_head_day > 0')
        batch_op.create_check_constraint('ck_feed_recipes_bulk_density_positive', 'bulk_density_kg_per_litre IS NULL OR bulk_density_kg_per_litre > 0')
        batch_op.create_check_constraint('ck_feed_recipes_bucket_volume_positive', 'bucket_volume_litres IS NULL OR bucket_volume_litres > 0')
        batch_op.create_check_constraint('ck_feed_recipes_scoop_weight_positive', 'scoop_weight_kg IS NULL OR scoop_weight_kg > 0')
    op.alter_column('feed_recipes', 'quantity_basis', server_default=None)


def downgrade():
    with op.batch_alter_table('feed_recipes') as batch_op:
        batch_op.drop_constraint('ck_feed_recipes_scoop_weight_positive', type_='check')
        batch_op.drop_constraint('ck_feed_recipes_bucket_volume_positive', type_='check')
        batch_op.drop_constraint('ck_feed_recipes_bulk_density_positive', type_='check')
        batch_op.drop_constraint('ck_feed_recipes_concentrate_rate_positive', type_='check')
        batch_op.drop_constraint('ck_feed_recipes_quantity_basis_valid', type_='check')
        batch_op.drop_column('scoop_weight_kg')
        batch_op.drop_column('bucket_volume_litres')
        batch_op.drop_column('bulk_density_kg_per_litre')
        batch_op.drop_column('concentrate_kg_per_head_day')
        batch_op.drop_column('quantity_basis')

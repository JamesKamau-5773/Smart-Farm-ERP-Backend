"""split breeding semen source

Revision ID: 1a2b3c4d5e7f
Revises: f4a2c8d1e7b9
Create Date: 2026-07-14 12:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = '1a2b3c4d5e7f'
down_revision = 'f4a2c8d1e7b9'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'breeding_logs',
        'semen_id',
        new_column_name='inventory_semen_id',
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        'breeding_logs',
        'inventory_semen_id',
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column('breeding_logs', sa.Column('external_sire_code', sa.String(length=100), nullable=True))
    op.add_column('breeding_logs', sa.Column('provided_by', sa.String(length=20), nullable=True))
    op.execute("UPDATE breeding_logs SET provided_by = 'FARM' WHERE provided_by IS NULL")
    op.alter_column('breeding_logs', 'provided_by', existing_type=sa.String(length=20), nullable=False)
    op.create_check_constraint(
        'ck_breeding_logs_provided_by_valid',
        'breeding_logs',
        "provided_by IN ('FARM', 'VET')",
    )


def downgrade():
    op.drop_constraint('ck_breeding_logs_provided_by_valid', 'breeding_logs', type_='check')
    op.drop_column('breeding_logs', 'provided_by')
    op.drop_column('breeding_logs', 'external_sire_code')
    op.alter_column(
        'breeding_logs',
        'inventory_semen_id',
        new_column_name='semen_id',
        existing_type=sa.Integer(),
        existing_nullable=True,
    )

"""Add cooperative metadata to tenants

Revision ID: ae11c7a9b24d
Revises: ea7d0c9f7b21
Create Date: 2026-07-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'ae11c7a9b24d'
down_revision = 'ea7d0c9f7b21'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tenants', sa.Column('region', sa.String(length=100), nullable=True))
    op.add_column('tenants', sa.Column('registration_number', sa.String(length=100), nullable=True))
    op.create_unique_constraint('uq_tenants_registration_number', 'tenants', ['registration_number'])


def downgrade():
    op.drop_constraint('uq_tenants_registration_number', 'tenants', type_='unique')
    op.drop_column('tenants', 'registration_number')
    op.drop_column('tenants', 'region')
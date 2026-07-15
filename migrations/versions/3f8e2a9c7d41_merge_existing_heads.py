"""Merge existing Alembic heads

Revision ID: 3f8e2a9c7d41
Revises: 1c9c4f7e2d11, 4a1d7e9c2b33, 5e8c2b6f4d71, 7c9d1d3a4f11, c2d9e7a1f4b6, d4f6c1a8b2e7
Create Date: 2026-07-03 00:00:00.000000
"""
from alembic import op


revision = '3f8e2a9c7d41'
down_revision = ('1c9c4f7e2d11', '4a1d7e9c2b33', '5e8c2b6f4d71', '7c9d1d3a4f11', 'c2d9e7a1f4b6', 'd4f6c1a8b2e7')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
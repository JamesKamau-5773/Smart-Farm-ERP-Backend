"""Merge vet and inventory migration heads.

Revision ID: 6a7d2f1b9c4e
Revises: 1c9c4f7e2d11, d4f6c1a8b2e7
Create Date: 2026-05-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = '6a7d2f1b9c4e'
down_revision = ('1c9c4f7e2d11', 'd4f6c1a8b2e7')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

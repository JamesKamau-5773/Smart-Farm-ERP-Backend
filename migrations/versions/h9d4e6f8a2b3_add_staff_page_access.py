"""Persist owner-managed page access for staff accounts.

Revision ID: h9d4e6f8a2b3
Revises: g8c3d5e7f9a1
Create Date: 2026-10-22 19:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'h9d4e6f8a2b3'
down_revision = 'g8c3d5e7f9a1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('page_access', sa.JSON(), nullable=True))
    # Give existing staff the same least-privilege starting permissions used
    # for new invitations. Farm owners can adjust these through Staff Registry.
    op.execute("""
        UPDATE users SET page_access = CASE UPPER(role)
            WHEN 'FARM_HAND' THEN '["production", "tasks", "herd", "feed"]'::json
            WHEN 'VETERINARY_DOCTOR' THEN '["herd", "breeding", "medical"]'::json
            WHEN 'FARM_SUPERVISOR' THEN '["production", "tasks", "herd", "breeding", "medical", "feed", "reports", "safety"]'::json
            WHEN 'FARM_MANAGER' THEN '["dashboard", "production", "tasks", "herd", "breeding", "medical", "feed", "customers", "reports", "safety"]'::json
            WHEN 'FARM_ADMIN' THEN '["dashboard", "production", "tasks", "herd", "breeding", "medical", "feed", "customers", "finance", "inventory", "reports", "safety", "staff", "payroll", "member_admin"]'::json
            ELSE NULL
        END
        WHERE role IS NOT NULL
    """)


def downgrade():
    op.drop_column('users', 'page_access')

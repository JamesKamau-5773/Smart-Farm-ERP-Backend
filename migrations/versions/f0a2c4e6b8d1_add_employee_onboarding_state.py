"""Add employee account onboarding state.

Revision ID: f0a2c4e6b8d1
Revises: e9a1c3d5f7b2
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa


revision = 'f0a2c4e6b8d1'
down_revision = 'e9a1c3d5f7b2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('requires_password_reset', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        'employees',
        sa.Column('onboarding_status', sa.String(length=30), server_default='NONE', nullable=False),
    )
    op.add_column('employees', sa.Column('onboarding_invite_nonce', sa.String(length=32), nullable=True))
    op.add_column(
        'employees',
        sa.Column('onboarding_invite_expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text(
        """
        UPDATE employees
        SET onboarding_status = 'ACTIVE'
        FROM users
        WHERE employees.user_id = users.id
          AND users.is_active = true
        """
    ))
    op.create_check_constraint(
        'ck_employees_onboarding_status_valid',
        'employees',
        "onboarding_status IN ('NONE', 'INVITE_PENDING', 'PASSWORD_RESET_REQUIRED', 'ACTIVE', 'DISABLED')",
    )


def downgrade():
    op.drop_constraint('ck_employees_onboarding_status_valid', 'employees', type_='check')
    op.drop_column('employees', 'onboarding_invite_expires_at')
    op.drop_column('employees', 'onboarding_invite_nonce')
    op.drop_column('employees', 'onboarding_status')
    op.drop_column('users', 'requires_password_reset')

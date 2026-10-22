"""Add hashed short-lived account invitation codes.

Revision ID: g8c3d5e7f9a1
Revises: f7b2c4d6e8a0
Create Date: 2026-10-22 19:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'g8c3d5e7f9a1'
down_revision = 'f7b2c4d6e8a0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'account_invitations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('purpose', sa.String(length=40), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=True),
        sa.Column('employee_nonce', sa.String(length=32), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_account_invitations_token_hash', 'account_invitations', ['token_hash'], unique=True)
    op.create_index('ix_account_invitations_account_id', 'account_invitations', ['account_id'])
    op.create_index('ix_account_invitations_tenant_id', 'account_invitations', ['tenant_id'])
    op.create_index('ix_account_invitations_employee_id', 'account_invitations', ['employee_id'])
    op.create_index('ix_account_invitations_expires_at', 'account_invitations', ['expires_at'])


def downgrade():
    op.drop_index('ix_account_invitations_expires_at', table_name='account_invitations')
    op.drop_index('ix_account_invitations_employee_id', table_name='account_invitations')
    op.drop_index('ix_account_invitations_tenant_id', table_name='account_invitations')
    op.drop_index('ix_account_invitations_account_id', table_name='account_invitations')
    op.drop_index('ix_account_invitations_token_hash', table_name='account_invitations')
    op.drop_table('account_invitations')

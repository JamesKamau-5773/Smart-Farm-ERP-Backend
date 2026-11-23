"""Two-factor authentication tables for the platform admin.

Revision ID: r0c1d2e3f4a5
Revises: q9b0c1d2e3f4
Create Date: 2026-11-23

New tables only: user_mfa_credentials (encrypted TOTP secret), user_mfa_recovery_codes
(hashed single-use codes) and mfa_sessions (token ids that passed 2FA). No existing
table or row is changed.
"""
from alembic import op
import sqlalchemy as sa


revision = 'r0c1d2e3f4a5'
down_revision = 'q9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_mfa_credentials',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('secret_ciphertext', sa.Text(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_step', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'user_mfa_recovery_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'code_hash', name='uq_user_mfa_recovery_codes_user_hash'),
    )
    op.create_index('ix_user_mfa_recovery_codes_user_id', 'user_mfa_recovery_codes', ['user_id'])
    op.create_table(
        'mfa_sessions',
        sa.Column('jti', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_mfa_sessions_user_id', 'mfa_sessions', ['user_id'])
    op.create_index('ix_mfa_sessions_expires_at', 'mfa_sessions', ['expires_at'])


def downgrade():
    # These tables hold only 2FA enrolment data created after this revision.
    op.drop_index('ix_mfa_sessions_expires_at', table_name='mfa_sessions')
    op.drop_index('ix_mfa_sessions_user_id', table_name='mfa_sessions')
    op.drop_table('mfa_sessions')
    op.drop_index('ix_user_mfa_recovery_codes_user_id', table_name='user_mfa_recovery_codes')
    op.drop_table('user_mfa_recovery_codes')
    op.drop_table('user_mfa_credentials')

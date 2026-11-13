"""Auth hardening: E.164 phones, verification flags, social accounts, challenges.

Data handling is report-only for anything ambiguous: invalid or conflicting
phone numbers and case-insensitive duplicate emails are written to
``account_data_issues`` (and logged) instead of being deleted or merged.
Preview the phone plan first with ``flask auth audit-phones``.

Revision ID: i1a2b3c4d5e6
Revises: h9d4e6f8a2b3
Create Date: 2026-11-02 12:00:00.000000
"""
import logging
from collections import defaultdict

from alembic import op
import sqlalchemy as sa

from app.utils.phone_backfill import UserPhoneRecord, plan_phone_backfill


revision = 'i1a2b3c4d5e6'
down_revision = 'h9d4e6f8a2b3'
branch_labels = None
depends_on = None

log = logging.getLogger('alembic.runtime.migration')


def upgrade():
    op.add_column('users', sa.Column('phone_verified', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('has_password', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))

    op.create_table(
        'social_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_user_id', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('provider', 'provider_user_id', name='uq_social_accounts_provider_subject'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_social_accounts_user_provider'),
    )
    op.create_index('ix_social_accounts_user_id', 'social_accounts', ['user_id'])

    op.create_table(
        'verification_challenges',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('public_id', sa.String(length=32), nullable=False, unique=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('purpose', sa.String(length=40), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('target', sa.String(length=255), nullable=False),
        sa.Column('secret_hash', sa.String(length=64), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_inbound_message_id', sa.String(length=128), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_verification_challenges_user_id', 'verification_challenges', ['user_id'])
    op.create_index('ix_verification_challenges_secret_hash', 'verification_challenges', ['secret_hash'])
    op.create_index('ix_verification_challenges_lookup', 'verification_challenges', ['purpose', 'target'])
    op.create_index(
        'ix_verification_challenges_last_inbound_message_id', 'verification_challenges', ['last_inbound_message_id'],
    )

    op.create_table(
        'account_data_issues',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field', sa.String(length=40), nullable=False),
        sa.Column('issue_type', sa.String(length=40), nullable=False),
        sa.Column('source', sa.String(length=40), nullable=True),
        sa.Column('raw_value', sa.String(length=255), nullable=True),
        sa.Column('normalized_value', sa.String(length=255), nullable=True),
        sa.Column('conflicting_user_id', sa.Integer(), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_account_data_issues_user_id', 'account_data_issues', ['user_id'])

    bind = op.get_bind()
    _normalize_phones(bind)
    _normalize_emails(bind)
    op.create_index('ix_users_email_lower', 'users', [sa.text('lower(email)')])


def _record_issues(bind, rows):
    if rows:
        bind.execute(sa.text("""
            INSERT INTO account_data_issues
                (user_id, field, issue_type, source, raw_value, normalized_value, conflicting_user_id)
            VALUES (:user_id, :field, :issue_type, :source, :raw_value, :normalized_value, :conflicting_user_id)
        """), rows)


def _normalize_phones(bind):
    rows = bind.execute(sa.text('SELECT id, phone_number, identifier, username FROM users ORDER BY id')).all()
    plan = plan_phone_backfill(UserPhoneRecord(*row) for row in rows)

    if plan.changes:
        changed_ids = list(plan.changes)
        # Clear first so values can move between rows without tripping the unique constraint.
        bind.execute(
            sa.text('UPDATE users SET phone_number = NULL WHERE id IN :ids').bindparams(sa.bindparam('ids', expanding=True)),
            {'ids': changed_ids},
        )
        updates = [{'id': user_id, 'phone': phone} for user_id, phone in plan.changes.items() if phone]
        if updates:
            bind.execute(sa.text('UPDATE users SET phone_number = :phone WHERE id = :id'), updates)

    _record_issues(bind, [
        {
            'user_id': issue.user_id,
            'field': 'phone_number',
            'issue_type': issue.issue_type,
            'source': issue.source,
            'raw_value': (issue.raw_value or '')[:255],
            'normalized_value': issue.normalized_value,
            'conflicting_user_id': issue.conflicting_user_id,
        }
        for issue in plan.issues
    ])
    log.info('Phone normalisation: %s', plan.summary())
    for issue in plan.issues:
        log.warning(
            'Phone issue %s for user %s (source=%s, raw=%r, normalized=%s, conflicts_with=%s)',
            issue.issue_type, issue.user_id, issue.source, issue.raw_value,
            issue.normalized_value, issue.conflicting_user_id,
        )


def _normalize_emails(bind):
    bind.execute(sa.text("UPDATE users SET email = NULL WHERE email IS NOT NULL AND trim(email) = ''"))
    rows = bind.execute(sa.text('SELECT id, email FROM users WHERE email IS NOT NULL ORDER BY id')).all()

    by_normalized = defaultdict(list)
    for user_id, email in rows:
        by_normalized[email.strip().lower()].append((user_id, email))

    updates, issues = [], []
    for normalized, owners in by_normalized.items():
        if len(owners) > 1:
            # Leave every original value untouched; report for manual resolution.
            first_id = owners[0][0]
            for user_id, email in owners:
                issues.append({
                    'user_id': user_id, 'field': 'email', 'issue_type': 'DUPLICATE_EMAIL', 'source': 'email',
                    'raw_value': email[:255], 'normalized_value': normalized,
                    'conflicting_user_id': first_id if user_id != first_id else owners[1][0],
                })
            continue
        user_id, email = owners[0]
        if email != normalized:
            updates.append({'id': user_id, 'email': normalized})

    if updates:
        bind.execute(sa.text('UPDATE users SET email = :email WHERE id = :id'), updates)
    _record_issues(bind, issues)
    log.info('Email normalisation: %s lowercased, %s duplicate rows reported', len(updates), len(issues))


def downgrade():
    op.drop_index('ix_users_email_lower', table_name='users')
    # Restore the previous digits-only phone format.
    op.execute(r"UPDATE users SET phone_number = regexp_replace(phone_number, '\D', '', 'g') WHERE phone_number IS NOT NULL")
    # Put back column values the upgrade cleared, before their report is dropped.
    op.execute("""
        UPDATE users SET phone_number = issue.raw_value
        FROM (
            SELECT DISTINCT ON (user_id) user_id, raw_value
            FROM account_data_issues
            WHERE field = 'phone_number' AND source = 'phone_number'
              AND issue_type IN ('INVALID_PHONE', 'AMBIGUOUS_PHONE', 'DUPLICATE_PHONE')
            ORDER BY user_id, id
        ) AS issue
        WHERE users.id = issue.user_id AND users.phone_number IS NULL
    """)
    op.drop_table('account_data_issues')
    op.drop_table('verification_challenges')
    op.drop_table('social_accounts')
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'has_password')
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'phone_verified')

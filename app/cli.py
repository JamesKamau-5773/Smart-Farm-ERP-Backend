"""Operator commands: ``flask auth audit-phones``, ``flask demo seed``, ``flask platform ...``.

The ``platform`` commands are the only way to reset the super admin's 2FA or move the
role. They run on the server, never over HTTP, and each prints exactly what it will
change first (all that --dry-run does), then asks for confirmation.
"""
from __future__ import annotations

import click
from flask.cli import AppGroup
from sqlalchemy import text

from app import db
from app.utils.phone_backfill import UserPhoneRecord, plan_phone_backfill

auth_cli = AppGroup('auth', help='Authentication maintenance commands.')


@auth_cli.command('audit-phones')
@click.option('--show-all', is_flag=True, help='List every planned change, not only issues.')
def audit_phones(show_all):
    """Dry run of the phone normalisation migration. Writes nothing."""
    rows = db.session.execute(text('SELECT id, phone_number, identifier, username FROM users ORDER BY id')).all()
    plan = plan_phone_backfill(UserPhoneRecord(*row) for row in rows)

    click.echo(f'Users scanned: {len(rows)}')
    for key, value in sorted(plan.summary().items()):
        click.echo(f'  {key}: {value}')
    for issue in plan.issues:
        click.echo(
            f'  [{issue.issue_type}] user={issue.user_id} source={issue.source} '
            f'raw={issue.raw_value!r} normalized={issue.normalized_value} conflicts_with={issue.conflicting_user_id}'
        )
    if show_all:
        for user_id, value in sorted(plan.changes.items()):
            click.echo(f'  [CHANGE] user={user_id} phone_number -> {value}')


demo_cli = AppGroup('demo', help='Public demo workspace ("Silato Farm").')


@demo_cli.command('seed')
@click.option('--if-missing', is_flag=True,
              help='Do nothing if the demo workspace already exists (used on every deploy).')
def seed_demo(if_missing):
    """Create or rebuild the demo workspace with data dated relative to today.

    Idempotent: replaces the demo tenant's data, never duplicates it. Runs
    whether or not DEMO_ENABLED is set, so the data can be prepared first.
    With --if-missing an existing workspace is left alone; the first visitor
    of each day refreshes its dates anyway.
    """
    from app.services.demo_account import DemoAccount
    from app.services.demo_seed_service import DemoSeedService

    if if_missing and DemoAccount.owner() is not None:
        click.echo('Demo workspace already exists; skipping seed.')
        return

    summary = DemoSeedService.seed()
    click.echo(f'Demo workspace ready (tenant {summary.tenant_id}).')
    for table, count in sorted(summary.counts.items()):
        click.echo(f'  {table}: {count}')


platform_cli = AppGroup('platform', help='Super admin recovery (server-side only).')

_REASON_HELP = 'Why this is being done (kept in the audit log). At least 10 characters.'


def _run_plan(plan, *, dry_run: bool, typed_confirmation: str | None = None) -> None:
    click.echo(plan.title)
    if plan.refused:
        raise click.ClickException(f'Refused: {plan.refusal} Nothing was changed.')
    for line in plan.changes:
        click.echo(f'  {line}')
    if dry_run:
        click.echo('Dry run: nothing was changed.')
        return
    if typed_confirmation:
        typed = click.prompt(f'Type {typed_confirmation} to confirm', default='', show_default=False)
        if typed.strip() != typed_confirmation:
            raise click.ClickException('Confirmation did not match. Nothing was changed.')
    elif not click.confirm('Apply these changes?', default=False):
        raise click.ClickException('Cancelled. Nothing was changed.')
    plan.apply()
    click.echo('Done.')


@platform_cli.command('reset-2fa')
@click.option('--reason', required=True, help=_REASON_HELP)
@click.option('--dry-run', is_flag=True, help='Show what would change and stop.')
def reset_2fa(reason, dry_run):
    """Clear the super admin's authenticator and recovery codes and end their sessions.

    They enrol two-factor authentication again at their next sign-in.
    """
    from app.services.platform_account_service import PlatformAccountService

    _run_plan(PlatformAccountService.plan_reset_2fa(reason), dry_run=dry_run)


@platform_cli.command('transfer-super-admin')
@click.option('--to', 'to_phone', required=True, help="Phone number of the account that becomes the super admin.")
@click.option('--reason', required=True, help=_REASON_HELP)
@click.option('--dry-run', is_flag=True, help='Show what would change and stop.')
def transfer_super_admin(to_phone, reason, dry_run):
    """Demote the current super admin and make another account the super admin, atomically."""
    from app.services.platform_account_service import PlatformAccountService
    from app.utils.phone import try_to_e164

    plan = PlatformAccountService.plan_transfer(to_phone, reason)
    _run_plan(plan, dry_run=dry_run, typed_confirmation=try_to_e164(to_phone) or to_phone)


@platform_cli.command('status')
def platform_status():
    """Read-only: the super admin, where it lives, its 2FA state and what its tenant holds."""
    from app.services.platform_account_service import PlatformAccountService

    report = PlatformAccountService.status()
    click.echo(f"Platform tenant: {report['platform_tenant_id'] or 'missing (run the migrations)'}")
    if not report['super_admins']:
        click.echo('Super admin: none')
    for admin in report['super_admins']:
        click.echo(
            f"Super admin: user {admin['user_id']} ({admin['username']}), active={admin['active']}, "
            f"tenant {admin['tenant_id']}, in platform tenant={admin['in_platform_tenant']}, "
            f"2FA enrolled={admin['mfa_enrolled']}"
        )
        contents = admin['tenant_contents']
        click.echo('  Its tenant also holds: ' + (', '.join(f'{t}: {n}' for t, n in contents.items()) or 'nothing'))


@platform_cli.command('move-super-admin')
@click.option('--reason', required=True, help=_REASON_HELP)
@click.option('--dry-run', is_flag=True, help='Show what would change and stop.')
def move_super_admin(reason, dry_run):
    """Move the super admin account into the platform tenant.

    Only when its current tenant holds no farm data; otherwise use split-super-admin.
    Changes only the account (its tenant, page access, sessions) and writes an audit entry.
    """
    from app.services.platform_account_service import PlatformAccountService

    _run_plan(PlatformAccountService.plan_move(reason), dry_run=dry_run)


@platform_cli.command('split-super-admin')
@click.option('--reason', required=True, help=_REASON_HELP)
@click.option('--username', required=True, help='Username for the new platform admin account.')
@click.option('--name', default='', help='Display name for the new account.')
@click.option('--email', default='', help='Optional email for the new account.')
@click.option('--dry-run', is_flag=True, help='Show what would change and stop.')
def split_super_admin(reason, username, name, email, dry_run):
    """For a super admin whose account runs a real farm.

    The current account becomes that farm's FARMER, keeping all its data, and a new
    account (password typed at a hidden prompt) becomes the super admin in the platform tenant.
    """
    from app.services.platform_account_service import PlatformAccountService

    preview = PlatformAccountService.plan_split(reason, username=username, name=name, email=email)
    if dry_run or preview.refused:
        _run_plan(preview, dry_run=True)
        return
    password = click.prompt('Password for the new platform admin account', hide_input=True,
                            confirmation_prompt=True)
    plan = PlatformAccountService.plan_split(reason, username=username, name=name, email=email, password=password)
    _run_plan(plan, dry_run=False, typed_confirmation=username.strip())


def register_cli(app) -> None:
    app.cli.add_command(auth_cli)
    app.cli.add_command(demo_cli)
    app.cli.add_command(platform_cli)

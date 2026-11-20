"""Operator commands: ``flask auth audit-phones``, ``flask demo seed``."""
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
def seed_demo():
    """Create or rebuild the demo workspace with data dated relative to today.

    Idempotent: replaces the demo tenant's data, never duplicates it. Runs
    whether or not DEMO_ENABLED is set, so the data can be prepared first.
    """
    from app.services.demo_seed_service import DemoSeedService

    summary = DemoSeedService.seed()
    click.echo(f'Demo workspace ready (tenant {summary.tenant_id}).')
    for table, count in sorted(summary.counts.items()):
        click.echo(f'  {table}: {count}')


def register_cli(app) -> None:
    app.cli.add_command(auth_cli)
    app.cli.add_command(demo_cli)

"""Operator commands: ``flask auth audit-phones``."""
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


def register_cli(app) -> None:
    app.cli.add_command(auth_cli)

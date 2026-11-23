"""Refuses to run the tests against anything but a throwaway local database.

Every test drops and recreates the whole schema, so pointing TEST_DATABASE_URL
at the development database (which holds the demo seed) or at a hosted
database would destroy its data. The tests stop before connecting when:

* TEST_DATABASE_URL is not set (TestConfig would otherwise fall back to a default);
* it names the same database as DATABASE_URL;
* its host is not local (localhost, 127.0.0.1, ::1, a Unix socket, or ``db``,
  the docker compose service); TEST_DATABASE_LOCAL_HOSTS adds more names;
* its database name does not contain "test".
"""
from __future__ import annotations

from typing import Mapping, Optional

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

LOCAL_HOSTS = frozenset({'localhost', '127.0.0.1', '::1', 'db'})


def _database_identity(url) -> tuple:
    return ((url.host or '').lower(), url.port or 5432, (url.database or '').lower())


def _extra_local_hosts(env: Mapping[str, str]) -> set:
    raw = env.get('TEST_DATABASE_LOCAL_HOSTS') or ''
    return {host.strip().lower() for host in raw.split(',') if host.strip()}


def problems(env: Mapping[str, str]) -> list:
    """Reasons TEST_DATABASE_URL is unsafe to wipe; empty when it is safe."""
    raw = (env.get('TEST_DATABASE_URL') or '').strip()
    if not raw:
        return ['TEST_DATABASE_URL is not set. Point it at a throwaway local database.']
    try:
        test_url = make_url(raw)
    except ArgumentError:
        return ['TEST_DATABASE_URL is not a valid database URL.']

    found = []
    host = (test_url.host or '').lower()
    if host and host not in LOCAL_HOSTS | _extra_local_hosts(env):
        hosted = ' (a Neon database)' if host.endswith('neon.tech') else ''
        found.append(f'TEST_DATABASE_URL points at a non-local host{hosted}: {host}.')

    if 'test' not in (test_url.database or '').lower():
        found.append('TEST_DATABASE_URL must name a database whose name contains "test".')

    app_raw = (env.get('DATABASE_URL') or '').strip()
    if app_raw:
        try:
            app_url: Optional[object] = make_url(app_raw)
        except ArgumentError:
            app_url = None
        if app_url is not None and _database_identity(app_url) == _database_identity(test_url):
            found.append('TEST_DATABASE_URL is the same database as DATABASE_URL.')
    return found


def assert_safe_test_database(env: Mapping[str, str]) -> None:
    found = problems(env)
    if found:
        raise RuntimeError(
            'Refusing to run the tests: they drop and recreate every table.\n- ' + '\n- '.join(found)
        )

"""The visitor's real IP address when the app runs behind a proxy.

On Render every request reaches gunicorn through Render's load balancers, so
``REMOTE_ADDR`` is one of a handful of internal 10.x addresses shared by every
visitor. Per-IP rate limits then throttle everyone together, and audit logs
record the proxy instead of the person.

Render serves traffic through Cloudflare, which sets ``True-Client-IP`` and
``CF-Connecting-IP`` to the connecting visitor and overwrites any value the
client sent, so those headers can be trusted. ``X-Forwarded-For`` cannot:
Render appends to whatever the client supplies.

This middleware copies the first trusted header that holds a single valid IP
into ``REMOTE_ADDR``, before Flask sees the request. Everything that reads
``request.remote_addr`` (rate limits, audit logs, receipts) and gunicorn's
access log then see the visitor. The proxy's address is kept in
``environ['client_ip.proxy_addr']``.

Only enable it where those headers are set by infrastructure you trust; on a
server reachable directly, a client could send any address.
"""
from __future__ import annotations

import ipaddress
from typing import Iterable, Optional

PROXY_ADDR_KEY = 'client_ip.proxy_addr'


def _environ_key(header: str) -> str:
    return 'HTTP_' + header.strip().upper().replace('-', '_')


def _single_ip(value: Optional[str]) -> Optional[str]:
    """The header's IP in canonical form, or None if it is not exactly one valid IP."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


class TrustedClientIPMiddleware:
    def __init__(self, wsgi_app, headers: Iterable[str]):
        self.wsgi_app = wsgi_app
        self.environ_keys = tuple(_environ_key(header) for header in headers if header.strip())

    def __call__(self, environ, start_response):
        for key in self.environ_keys:
            client_ip = _single_ip(environ.get(key))
            if client_ip:
                environ[PROXY_ADDR_KEY] = environ.get('REMOTE_ADDR')
                environ['REMOTE_ADDR'] = client_ip
                break
        return self.wsgi_app(environ, start_response)


def install(app) -> None:
    """Wrap the app when CLIENT_IP_HEADERS is configured; otherwise leave REMOTE_ADDR alone."""
    headers = tuple(app.config.get('CLIENT_IP_HEADERS') or ())
    if headers:
        app.wsgi_app = TrustedClientIPMiddleware(app.wsgi_app, headers)

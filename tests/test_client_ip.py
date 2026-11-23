"""Visitor IP behind Render's proxies: trusted headers replace the proxy's REMOTE_ADDR."""
import unittest

from app.utils.client_ip import PROXY_ADDR_KEY, TrustedClientIPMiddleware, install
from config import TestConfig
from tests.base import BaseTestCase

HEADERS = ('True-Client-IP', 'CF-Connecting-IP')
PROXY = '10.194.168.150'


def _run(environ, headers=HEADERS):
    seen = {}

    def wsgi_app(env, start_response):
        seen.update(env)
        start_response('200 OK', [])
        return [b'']

    TrustedClientIPMiddleware(wsgi_app, headers)({'REMOTE_ADDR': PROXY, **environ}, lambda *a: None)
    return seen


class TrustedClientIPMiddlewareTests(unittest.TestCase):
    def test_uses_the_first_trusted_header(self):
        env = _run({'HTTP_TRUE_CLIENT_IP': '41.90.1.2', 'HTTP_CF_CONNECTING_IP': '41.90.9.9'})
        self.assertEqual(env['REMOTE_ADDR'], '41.90.1.2')
        self.assertEqual(env[PROXY_ADDR_KEY], PROXY)

    def test_falls_back_to_the_next_header(self):
        self.assertEqual(_run({'HTTP_CF_CONNECTING_IP': '41.90.9.9'})['REMOTE_ADDR'], '41.90.9.9')

    def test_normalises_ipv6(self):
        env = _run({'HTTP_TRUE_CLIENT_IP': ' 2001:DB8:0:0:0:0:0:1 '})
        self.assertEqual(env['REMOTE_ADDR'], '2001:db8::1')

    def test_keeps_the_socket_address_without_a_valid_single_ip(self):
        for value in ('', 'not-an-ip', '41.90.1.2, 41.90.1.3', '41.90.1.2:443'):
            with self.subTest(value=value):
                env = _run({'HTTP_TRUE_CLIENT_IP': value})
                self.assertEqual(env['REMOTE_ADDR'], PROXY)
                self.assertNotIn(PROXY_ADDR_KEY, env)

    def test_x_forwarded_for_is_never_trusted(self):
        env = _run({'HTTP_X_FORWARDED_FOR': '1.2.3.4'})
        self.assertEqual(env['REMOTE_ADDR'], PROXY)


class ClientIPConfigTests(unittest.TestCase):
    def test_install_does_nothing_without_configured_headers(self):
        class FakeApp:
            config = {'CLIENT_IP_HEADERS': ()}
            wsgi_app = object()

        original = FakeApp.wsgi_app
        install(FakeApp)
        self.assertIs(FakeApp.wsgi_app, original)


class ProxiedConfig(TestConfig):
    CLIENT_IP_HEADERS = HEADERS


class RateLimitsBehindProxyTests(BaseTestCase):
    """Every visitor arrives from the same proxy address, as on Render."""

    def setUp(self):
        from app import create_app

        super().setUp()
        self.proxied = create_app(ProxiedConfig).test_client(use_cookies=False)

    def _google_start(self, visitor_ip):
        return self.proxied.get(
            '/api/auth/google/start',
            headers={'True-Client-IP': visitor_ip},
            environ_base={'REMOTE_ADDR': PROXY},
        ).status_code

    def test_one_visitor_hitting_the_limit_does_not_block_others(self):
        statuses = [self._google_start('41.90.50.1') for _ in range(11)]
        self.assertEqual(statuses[-1], 429)
        self.assertNotEqual(self._google_start('41.90.50.2'), 429)

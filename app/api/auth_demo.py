"""POST /api/auth/demo: start a read-only session on the public demo farm."""
from flask import Blueprint, abort, current_app, request

from app import limiter
from app.services.demo_account import DemoAccount
from app.services.demo_session_service import DemoSessionService

auth_demo_bp = Blueprint('auth_demo', __name__)


def _client_ip() -> str:
    # Always per IP: the default key is tenant/user based, and every demo
    # visitor shares the same tenant and user.
    return f'demo-ip:{request.remote_addr}'


@auth_demo_bp.route('/demo', methods=['POST'])
@limiter.limit(
    lambda: current_app.config.get('DEMO_LOGIN_RATE_LIMIT') or '5 per minute;20 per hour',
    key_func=_client_ip,
    exempt_when=lambda: not DemoAccount.is_enabled(),
)
def start_demo_session():
    if not DemoAccount.is_enabled():
        abort(404)
    return DemoSessionService.start()

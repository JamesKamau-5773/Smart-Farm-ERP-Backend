"""Google sign-in (OAuth 2.0 redirect flow).

The browser navigates to /google/start, Google returns to /google/callback, and
the callback redirects to the frontend with a non-sensitive ``result`` code.
Sessions are set as cookies on that redirect, never passed in the URL.
"""
from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, redirect, request, session, url_for
from flask_jwt_extended import get_jwt_identity, jwt_required, set_access_cookies, verify_jwt_in_request

from app import limiter
from app.repositories.user_repo import UserRepository
from app.services.account_state_service import AccountStateService
from app.services.auth_service import AuthService
from app.services.google_identity_provider import GoogleAuthError, GoogleIdentityProvider
from app.services.session_service import AuthMethod
from app.services.social_login_service import (
    SIGNUP_TICKET_TTL_SECONDS,
    SignupTicketCodec,
    SocialLoginResult,
    SocialLoginService,
)
from app.utils.auth_errors import AuthError
from app.utils.current_user import require_current_user

auth_google_bp = Blueprint('auth_google', __name__)

SIGNUP_COOKIE = 'google_signup'
SIGNUP_COOKIE_PATH = '/api/auth/google'
OAUTH_CONTEXT_KEY = 'google_oauth_context'
INTENT_SIGNIN = 'signin'
INTENT_LINK = 'link'


def _safe_next(value):
    """Only same-site relative paths, to prevent open redirects."""
    value = (value or '').strip()
    if value.startswith('/') and not value.startswith('//') and '\\' not in value:
        return value
    return None


def _frontend_redirect(result, *, error_code=None, next_path=None):
    params = {'result': result}
    if error_code:
        params['error_code'] = error_code
    if next_path:
        params['next'] = next_path
    base = current_app.config['FRONTEND_BASE_URL'].rstrip('/')
    return redirect(f'{base}/auth/google/complete?{urlencode(params)}', code=302)


def _issue_google_session(user):
    tenant, farms = AuthService._ensure_default_tenant_and_farm(user)
    active_farm = AuthService._pick_active_farm(tenant=tenant, farms=farms, requested_farm_id=None)
    return AuthService._issue_token_and_payload(
        user=user, tenant=tenant, farms=farms, active_farm=active_farm, auth_method=AuthMethod.GOOGLE,
    )


def _set_signup_cookie(response, ticket):
    response.set_cookie(
        SIGNUP_COOKIE,
        ticket,
        max_age=SIGNUP_TICKET_TTL_SECONDS,
        httponly=True,
        secure=current_app.config.get('JWT_COOKIE_SECURE', False),
        samesite=current_app.config.get('JWT_COOKIE_SAMESITE', 'Lax'),
        path=SIGNUP_COOKIE_PATH,
    )


@auth_google_bp.route('/google/start', methods=['GET'])
@limiter.limit("10 per minute")
def google_start():
    next_path = _safe_next(request.args.get('next'))
    if not GoogleIdentityProvider.is_configured():
        return _frontend_redirect(SocialLoginResult.ERROR, error_code='GOOGLE_UNAVAILABLE', next_path=next_path)

    intent = request.args.get('intent', INTENT_SIGNIN)
    link_user_id = None
    if intent == INTENT_LINK:
        verify_jwt_in_request(optional=True)
        link_user_id = get_jwt_identity()
        if not link_user_id:
            return _frontend_redirect(SocialLoginResult.ERROR, error_code='UNAUTHENTICATED', next_path=next_path)
    else:
        intent = INTENT_SIGNIN

    session[OAUTH_CONTEXT_KEY] = {'intent': intent, 'next': next_path, 'link_user_id': link_user_id}
    redirect_uri = current_app.config.get('GOOGLE_REDIRECT_URI') or url_for('auth_google.google_callback', _external=True)
    return GoogleIdentityProvider.authorization_redirect(redirect_uri)


@auth_google_bp.route('/google/callback', methods=['GET'])
def google_callback():
    context = session.pop(OAUTH_CONTEXT_KEY, None) or {}
    next_path = context.get('next')
    try:
        identity = GoogleIdentityProvider.fetch_identity()
    except GoogleAuthError as error:
        return _frontend_redirect(SocialLoginResult.ERROR, error_code=error.code, next_path=next_path)

    if context.get('intent') == INTENT_LINK:
        verify_jwt_in_request(optional=True)
        current_user_id = get_jwt_identity()
        user = UserRepository.get_by_id(int(current_user_id)) if current_user_id else None
        if not user or str(current_user_id) != str(context.get('link_user_id')):
            return _frontend_redirect(SocialLoginResult.ERROR, error_code='UNAUTHENTICATED', next_path=next_path)
        outcome = SocialLoginService.link(identity, user)
        return _frontend_redirect(outcome.result, error_code=outcome.error_code, next_path=next_path)

    outcome = SocialLoginService.sign_in(identity)
    response = _frontend_redirect(outcome.result, error_code=outcome.error_code, next_path=next_path)
    if outcome.result == SocialLoginResult.SIGNUP_REQUIRED:
        _set_signup_cookie(response, outcome.signup_ticket)
    elif outcome.result in {SocialLoginResult.SIGNED_IN, SocialLoginResult.PHONE_VERIFICATION_REQUIRED}:
        access_token, _ = _issue_google_session(outcome.user)
        set_access_cookies(response, access_token)
    return response


@auth_google_bp.route('/google/pending-signup', methods=['GET'])
def google_pending_signup():
    ticket = request.cookies.get(SIGNUP_COOKIE)
    try:
        identity = SignupTicketCodec.decode(ticket)
    except AuthError:
        raise AuthError('SIGNUP_SESSION_EXPIRED', 'Your Google sign-up session has expired. Please start again.', 404)
    return jsonify({
        # Returned in the body so the signup POST does not depend on a
        # cross-site cookie; readable only by allowed CORS origins.
        'signup_token': ticket,
        'email': identity.email,
        'name': identity.name,
        'expires_in_seconds': SignupTicketCodec.remaining_seconds(ticket),
    }), 200


@auth_google_bp.route('/google/signup', methods=['POST'])
@limiter.limit("5 per 10 minutes")
def google_signup():
    data = request.get_json(silent=True) or {}
    user, tenant, farm, verification = SocialLoginService.complete_signup(data, ip_address=request.remote_addr)
    access_token, payload = AuthService._issue_token_and_payload(
        user=user, tenant=tenant, farms=[farm], active_farm=farm, auth_method=AuthMethod.GOOGLE,
    )
    response = jsonify({
        'message': 'Workspace registered successfully',
        'access_token': access_token,
        **payload,
        'phone_verification': verification,
    })
    set_access_cookies(response, access_token)
    response.delete_cookie(SIGNUP_COOKIE, path=SIGNUP_COOKIE_PATH)
    return response, 201


@auth_google_bp.route('/social/google', methods=['DELETE'])
@jwt_required()
def unlink_google():
    user = require_current_user()
    SocialLoginService.unlink(user)
    return jsonify({'message': 'Google account unlinked', 'account_flags': AccountStateService.account_flags(user)}), 200

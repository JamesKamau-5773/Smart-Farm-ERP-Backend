"""Adapter over Authlib's Google OpenID Connect client.

Only this module talks to Google; account decisions live in SocialLoginService.
"""
from __future__ import annotations

from dataclasses import dataclass

from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError
from authlib.integrations.flask_client import OAuth
from flask import current_app, request

GOOGLE_DISCOVERY_URL = 'https://accounts.google.com/.well-known/openid-configuration'

oauth = OAuth()


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str


class GoogleAuthError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class GoogleIdentityProvider:
    @staticmethod
    def init_app(app) -> None:
        oauth.init_app(app)
        if app.config.get('GOOGLE_CLIENT_ID') and app.config.get('GOOGLE_CLIENT_SECRET'):
            oauth.register(
                name='google',
                client_id=app.config['GOOGLE_CLIENT_ID'],
                client_secret=app.config['GOOGLE_CLIENT_SECRET'],
                server_metadata_url=GOOGLE_DISCOVERY_URL,
                client_kwargs={'scope': 'openid email profile'},
                overwrite=True,
            )

    @staticmethod
    def is_configured() -> bool:
        return bool(current_app.config.get('GOOGLE_CLIENT_ID') and current_app.config.get('GOOGLE_CLIENT_SECRET'))

    @staticmethod
    def authorization_redirect(redirect_uri: str):
        """Returns the 302 to Google; Authlib keeps state and nonce in the Flask session."""
        return oauth.create_client('google').authorize_redirect(redirect_uri)

    @staticmethod
    def fetch_identity() -> GoogleIdentity:
        if request.args.get('error'):
            raise GoogleAuthError('GOOGLE_CANCELLED' if request.args['error'] == 'access_denied' else 'GOOGLE_UNAVAILABLE')
        client = oauth.create_client('google')
        try:
            token = client.authorize_access_token()
        except MismatchingStateError as error:
            raise GoogleAuthError('GOOGLE_STATE_MISMATCH') from error
        except OAuthError as error:
            raise GoogleAuthError('GOOGLE_UNAVAILABLE') from error

        userinfo = token.get('userinfo') or {}
        subject = userinfo.get('sub')
        if not subject:
            raise GoogleAuthError('GOOGLE_UNAVAILABLE')
        return GoogleIdentity(
            subject=str(subject),
            email=(userinfo.get('email') or '').strip().lower(),
            email_verified=bool(userinfo.get('email_verified')),
            name=(userinfo.get('name') or '').strip(),
        )

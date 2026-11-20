"""Session claims and whole-account session revocation.

There are no refresh tokens; access tokens carry the user's ``token_version``
(claim ``tv``). Incrementing the version invalidates every token issued before
it, which is how password resets end all live sessions. Tokens issued before
this claim existed carry no ``tv`` and are treated as version 0.
"""
from __future__ import annotations

from app import db
from app.models.user import User


class AuthMethod:
    PASSWORD = 'password'
    GOOGLE = 'google'
    DEMO = 'demo'


class SessionService:
    TOKEN_VERSION_CLAIM = 'tv'
    AUTH_METHOD_CLAIM = 'amr'

    @staticmethod
    def session_claims(user: User, auth_method: str = AuthMethod.PASSWORD) -> dict:
        return {
            SessionService.TOKEN_VERSION_CLAIM: user.token_version or 0,
            SessionService.AUTH_METHOD_CLAIM: auth_method or AuthMethod.PASSWORD,
        }

    @staticmethod
    def auth_method_from_claims(claims: dict) -> str:
        return (claims or {}).get(SessionService.AUTH_METHOD_CLAIM) or AuthMethod.PASSWORD

    @staticmethod
    def revoke_all_sessions(user: User) -> None:
        """Invalidates every token issued so far. The caller commits."""
        user.token_version = (user.token_version or 0) + 1

    @staticmethod
    def is_token_current(jwt_payload: dict) -> bool:
        subject = (jwt_payload or {}).get('sub')
        try:
            user_id = int(subject)
        except (TypeError, ValueError):
            return True
        token_version = db.session.query(User.token_version).filter(User.id == user_id).scalar()
        if token_version is None:
            return True
        return int(jwt_payload.get(SessionService.TOKEN_VERSION_CLAIM, 0) or 0) == int(token_version)

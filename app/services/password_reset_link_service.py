"""One-time password reset links shared by the WhatsApp, email and admin flows."""
from __future__ import annotations

from dataclasses import dataclass

from app import db
from app.models.auth import ChallengePurpose, VerificationChallenge
from app.models.user import User
from app.repositories.verification_challenge_repo import VerificationChallengeRepository
from app.services import auth_message_templates as templates
from app.services.audit_service import record_audit
from app.services.session_service import SessionService
from app.services.verification_challenge_service import VerificationChallengeService
from app.utils.auth_errors import AuthError
from app.utils.password_policy import PasswordPolicy

PURPOSE = ChallengePurpose.PASSWORD_RESET_LINK
RESET_PURPOSES = (ChallengePurpose.PASSWORD_RESET_CODE, ChallengePurpose.PASSWORD_RESET_LINK)


@dataclass(frozen=True)
class ResetLink:
    url: str
    challenge: VerificationChallenge


def _invalid_token_error() -> AuthError:
    return AuthError('RESET_TOKEN_INVALID', 'This reset link is invalid or has expired.')


class PasswordResetLinkService:
    @staticmethod
    def issue(user: User, *, channel: str, target: str, created_by_id=None, ip_address=None) -> ResetLink:
        """Creates a reset link. The caller commits."""
        issued = VerificationChallengeService.issue_link_token(
            user, purpose=PURPOSE, target=target, channel=channel,
            created_by_id=created_by_id, ip_address=ip_address,
        )
        return ResetLink(url=templates.reset_password_url(issued.secret), challenge=issued.challenge)

    @staticmethod
    def validate(token: str) -> dict:
        challenge = PasswordResetLinkService._pending(token)
        return {'valid': True, 'expires_at': challenge.expires_at.isoformat()}

    @staticmethod
    def reset(token: str, password: str, confirm_password: str, *, ip_address=None) -> dict:
        challenge = PasswordResetLinkService._pending(token)
        user = challenge.user

        try:
            if password != confirm_password:
                raise AuthError('PASSWORD_MISMATCH', 'password and confirm_password must match.')
            PasswordPolicy.enforce(password, personal_values=PasswordPolicy.personal_values_for(user))
        except AuthError:
            VerificationChallengeService.record_failed_attempt(challenge)
            db.session.commit()
            raise

        user.set_password(password)
        user.requires_password_reset = False
        VerificationChallengeService.consume(challenge)
        VerificationChallengeRepository.cancel_open_for_user(user.id, RESET_PURPOSES)
        SessionService.revoke_all_sessions(user)
        record_audit(
            user_id=user.id,
            action='PASSWORD_RESET',
            entity_type='User',
            entity_id=user.id,
            old_value={'channel': challenge.channel},
            new_value={'sessions_revoked': True},
            ip_address=ip_address,
        )
        db.session.commit()
        return {'message': 'Password updated. Please log in with your new password.'}

    @staticmethod
    def _pending(token: str) -> VerificationChallenge:
        challenge = VerificationChallengeService.find_pending_by_token(purpose=PURPOSE, token=token)
        if not challenge or not challenge.user or not challenge.user.is_active:
            raise _invalid_token_error()
        return challenge

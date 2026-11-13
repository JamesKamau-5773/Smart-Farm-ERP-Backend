from __future__ import annotations

import logging

from app import db
from app.models.auth import ChallengePurpose
from app.models.user import User
from app.services import auth_message_templates as templates
from app.services.email_sender import dispatch_email, email_delivery_enabled
from app.services.verification_challenge_service import VerificationChallengeService
from app.utils.auth_errors import AuthError

log = logging.getLogger(__name__)

PURPOSE = ChallengePurpose.EMAIL_VERIFICATION


class EmailVerificationService:
    @staticmethod
    def send(user: User, *, ip_address=None) -> dict:
        if not user.email:
            raise AuthError('EMAIL_REQUIRED', 'Add an email address to your account first.')
        if user.email_verified:
            raise AuthError('EMAIL_ALREADY_VERIFIED', 'This email address is already verified.', 409)
        if not email_delivery_enabled():
            raise AuthError('CHANNEL_DISABLED', 'Email delivery is not available.')

        issued = VerificationChallengeService.issue_link_token(
            user, purpose=PURPOSE, target=user.email, channel='email', ip_address=ip_address,
        )
        db.session.commit()

        ttl_seconds = int(VerificationChallengeService.ttl().total_seconds())
        dispatch_email(templates.email_verification_email(
            user.email, templates.verify_email_url(issued.secret), ttl_seconds,
        ))
        return {'message': 'Verification email sent.', 'email': user.email, 'expires_in_seconds': ttl_seconds}

    @staticmethod
    def send_if_possible(user: User, *, ip_address=None) -> None:
        """Best-effort send used after registration or an email change."""
        try:
            EmailVerificationService.send(user, ip_address=ip_address)
        except AuthError as error:
            log.info('Skipped email verification for user %s: %s', user.id, error.code)

    @staticmethod
    def confirm(token: str) -> dict:
        challenge = VerificationChallengeService.find_pending_by_token(purpose=PURPOSE, token=token)
        user = challenge.user if challenge else None
        # The address must not have changed since the link was issued.
        if not challenge or not user or (user.email or '') != challenge.target:
            raise AuthError('VERIFICATION_TOKEN_INVALID', 'This verification link is invalid or has expired.')

        user.email_verified = True
        VerificationChallengeService.consume(challenge)
        db.session.commit()
        return {'message': 'Email verified.', 'email_verified': True}

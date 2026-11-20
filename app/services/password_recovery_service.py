"""Self-service "forgot password" requests.

Every request returns the same response whether or not an account exists, so
the endpoints cannot be used to discover accounts.
"""
from __future__ import annotations

from typing import Optional

from flask import current_app

from app import db
from app.models.auth import ChallengePurpose
from app.repositories.user_repo import UserRepository
from app.services import auth_message_templates as templates
from app.services.email_sender import dispatch_email, email_delivery_enabled
from app.services.password_reset_link_service import PasswordResetLinkService
from app.services.verification_challenge_service import CodeMatchStatus, VerificationChallengeService
from app.utils.auth_errors import AuthError, invalid_phone_error
from app.utils.phone import InvalidPhoneNumber, to_e164

GENERIC_MESSAGE = "If an account exists, we've sent instructions."
CODE_PURPOSE = ChallengePurpose.PASSWORD_RESET_CODE


class RecoveryChannel:
    WHATSAPP = 'whatsapp'
    EMAIL = 'email'


class PasswordRecoveryService:
    @staticmethod
    def whatsapp_enabled() -> bool:
        config = current_app.config
        return bool(config.get('WHATSAPP_BUSINESS_NUMBER') and config.get('WHATSAPP_ACCESS_TOKEN'))

    @staticmethod
    def options() -> dict:
        return {
            'channels': [
                {'id': RecoveryChannel.WHATSAPP, 'enabled': PasswordRecoveryService.whatsapp_enabled(),
                 'input': 'phone_number', 'label': 'WhatsApp'},
                {'id': RecoveryChannel.EMAIL, 'enabled': email_delivery_enabled(),
                 'input': 'email', 'label': 'Email'},
            ],
            'admin_reset_hint': 'Staff members can also ask their farm owner or administrator to reset their password.',
        }

    @staticmethod
    def request(data: dict, *, ip_address=None) -> dict:
        channel = (data.get('channel') or '').strip().lower()
        if channel == RecoveryChannel.WHATSAPP:
            return PasswordRecoveryService._request_whatsapp(data.get('phone_number'), ip_address)
        if channel == RecoveryChannel.EMAIL:
            return PasswordRecoveryService._request_email(data.get('email'), ip_address)
        raise AuthError('VALIDATION_ERROR', "channel must be 'whatsapp' or 'email'.", fields={'channel': 'invalid'})

    @staticmethod
    def _request_whatsapp(raw_phone: Optional[str], ip_address) -> dict:
        if not PasswordRecoveryService.whatsapp_enabled():
            raise AuthError('CHANNEL_DISABLED', 'WhatsApp recovery is not available.')
        try:
            phone = to_e164(raw_phone)
        except InvalidPhoneNumber:
            raise invalid_phone_error()

        user = UserRepository.get_by_phone(phone)
        if user and user.is_active:
            issued = VerificationChallengeService.issue_code(
                user, purpose=CODE_PURPOSE, target=phone, ip_address=ip_address,
            )
            db.session.commit()
            message_text = issued.message_text
        else:
            # Same shape as a real code; it can never match anything.
            message_text = VerificationChallengeService.generate_decoy_code(CODE_PURPOSE)

        return {
            'message': GENERIC_MESSAGE,
            'channel': RecoveryChannel.WHATSAPP,
            'message_text': message_text,
            'whatsapp_number': templates.whatsapp_business_number(),
            'wa_link': templates.wa_link(message_text),
            'expires_in_seconds': int(VerificationChallengeService.ttl().total_seconds()),
        }

    @staticmethod
    def _request_email(raw_email: Optional[str], ip_address) -> dict:
        if not email_delivery_enabled():
            raise AuthError('CHANNEL_DISABLED', 'Email recovery is not available.')
        email = (raw_email or '').strip().lower()
        if '@' not in email or len(email) > 254:
            raise AuthError('VALIDATION_ERROR', 'email must be a valid email address.', fields={'email': 'invalid'})

        ttl_seconds = int(VerificationChallengeService.ttl().total_seconds())
        user = UserRepository.get_by_email_ci(email)
        if user and user.is_active and user.email_verified:
            link = PasswordResetLinkService.issue(user, channel=RecoveryChannel.EMAIL, target=email, ip_address=ip_address)
            db.session.commit()
            dispatch_email(templates.password_reset_email(email, link.url, ttl_seconds))

        return {'message': GENERIC_MESSAGE, 'channel': RecoveryChannel.EMAIL, 'expires_in_seconds': ttl_seconds}

    @staticmethod
    def complete_whatsapp_code(*, sender: str, code: str, message_id: Optional[str]) -> str:
        """Handles an inbound ``RESET-xxxxxx`` message and returns the reply text.

        Receiving the reply link on the registered number is the proof of
        possession, so the reset link is only ever sent to that number.
        """
        match = VerificationChallengeService.match_code_from_sender(
            purpose=CODE_PURPOSE, sender=sender, code=code, message_id=message_id,
        )
        if match.status != CodeMatchStatus.MATCHED:
            db.session.commit()
            return templates.WHATSAPP_CODE_INVALID

        challenge = match.challenge
        user = challenge.user
        VerificationChallengeService.consume(challenge)
        if user.phone_number == sender:
            user.phone_verified = True
        link = PasswordResetLinkService.issue(user, channel=RecoveryChannel.WHATSAPP, target=sender)
        db.session.commit()
        return templates.whatsapp_reset_link_reply(link.url, int(VerificationChallengeService.ttl().total_seconds()))

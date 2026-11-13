"""Recognises inbound ``VERIFY-xxxxxx`` / ``RESET-xxxxxx`` WhatsApp messages."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.repositories.verification_challenge_repo import VerificationChallengeRepository
from app.services.password_recovery_service import PasswordRecoveryService
from app.services.phone_verification_service import PhoneVerificationService

REVERSE_OTP_PATTERN = re.compile(r'^\s*(VERIFY|RESET)\s*-?\s*(\d{6})\s*$', re.IGNORECASE)


@dataclass(frozen=True)
class InboundResult:
    handled: bool
    reply: Optional[str] = None


NOT_HANDLED = InboundResult(handled=False)


def _message_text(message: dict) -> str:
    if message.get('type') != 'text':
        return ''
    return ((message.get('text') or {}).get('body') or '')


class ReverseOtpMessageHandler:
    @staticmethod
    def handle(message: dict, *, sender: str) -> InboundResult:
        match = REVERSE_OTP_PATTERN.match(_message_text(message))
        if not match:
            return NOT_HANDLED

        message_id = message.get('id')
        # Meta retries deliveries; a replay must not burn attempts or re-reply.
        if VerificationChallengeRepository.message_already_processed(message_id):
            return InboundResult(handled=True)

        kind, code = match.group(1).upper(), match.group(2)
        if kind == 'VERIFY':
            reply = PhoneVerificationService.complete_from_whatsapp(sender=sender, code=code, message_id=message_id)
        else:
            reply = PasswordRecoveryService.complete_whatsapp_code(sender=sender, code=code, message_id=message_id)
        return InboundResult(handled=True, reply=reply)

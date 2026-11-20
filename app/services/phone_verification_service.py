"""Phone verification by WhatsApp reverse OTP.

The user is shown ``VERIFY-123456`` and sends it from their own WhatsApp. The
number is applied to the account only once possession is proven, and verified
possession wins over an unverified claim to the same number on another account.
"""
from __future__ import annotations

from typing import Optional

from app import db
from app.models.auth import AccountDataIssue, AccountDataIssueType, ChallengePurpose, ChallengeStatus
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.repositories.verification_challenge_repo import VerificationChallengeRepository
from app.services import auth_message_templates as templates
from app.services.audit_service import record_audit
from app.services.verification_challenge_service import CodeMatchStatus, VerificationChallengeService
from app.utils.auth_errors import AuthError, invalid_phone_error
from app.utils.phone import InvalidPhoneNumber, to_e164

PURPOSE = ChallengePurpose.PHONE_VERIFICATION


class PhoneVerificationService:
    @staticmethod
    def start(user: User, raw_phone: Optional[str] = None, *, ip_address=None) -> dict:
        # Without a business number the wa.me link has no recipient and the code can never arrive.
        if not templates.whatsapp_business_number():
            raise AuthError('CHANNEL_DISABLED', 'WhatsApp verification is not available right now.', 503)
        target = PhoneVerificationService._resolve_target(user, raw_phone)

        if target == user.phone_number and user.phone_verified:
            raise AuthError('PHONE_ALREADY_VERIFIED', 'This phone number is already verified.', 409)

        holder = UserRepository.get_by_phone(target)
        if holder and holder.id != user.id and holder.phone_verified:
            raise AuthError('PHONE_IN_USE', 'phone_number is already in use by another account.', 409)

        issued = VerificationChallengeService.issue_code(user, purpose=PURPOSE, target=target, ip_address=ip_address)
        db.session.commit()

        challenge = issued.challenge
        return {
            'verification_id': challenge.public_id,
            'status': challenge.status,
            'phone_number': target,
            'message_text': issued.message_text,
            'whatsapp_number': templates.whatsapp_business_number(),
            'wa_link': templates.wa_link(issued.message_text),
            'expires_at': challenge.expires_at.isoformat(),
            'expires_in_seconds': int(VerificationChallengeService.ttl().total_seconds()),
        }

    @staticmethod
    def status(user: User, verification_id: str) -> dict:
        challenge = VerificationChallengeRepository.get_for_user(verification_id, user.id)
        if not challenge or challenge.purpose != PURPOSE:
            raise AuthError('NOT_FOUND', 'Verification not found.', 404)
        status = challenge.status
        if status == ChallengeStatus.CONSUMED:
            status = ChallengeStatus.VERIFIED
        return {
            'verification_id': challenge.public_id,
            'status': status,
            'expires_at': challenge.expires_at.isoformat(),
            'attempts_remaining': challenge.attempts_remaining,
        }

    @staticmethod
    def complete_from_whatsapp(*, sender: str, code: str, message_id: Optional[str]) -> str:
        """Handles an inbound ``VERIFY-xxxxxx`` message and returns the reply text."""
        match = VerificationChallengeService.match_code_from_sender(
            purpose=PURPOSE, sender=sender, code=code, message_id=message_id,
        )
        if match.status != CodeMatchStatus.MATCHED:
            db.session.commit()
            return templates.WHATSAPP_CODE_INVALID

        challenge = match.challenge
        user = challenge.user
        holder = UserRepository.get_by_phone(sender)
        if holder and holder.id != user.id:
            if holder.phone_verified:
                VerificationChallengeService.cancel(challenge)
                db.session.commit()
                return templates.WHATSAPP_PHONE_TAKEN
            PhoneVerificationService._reclaim(holder, sender, new_owner=user)

        user.phone_number = sender
        user.phone_verified = True
        VerificationChallengeService.consume(challenge)
        db.session.commit()
        return templates.WHATSAPP_PHONE_VERIFIED

    @staticmethod
    def _resolve_target(user: User, raw_phone: Optional[str]) -> str:
        if raw_phone:
            try:
                return to_e164(raw_phone)
            except InvalidPhoneNumber:
                raise invalid_phone_error()
        if user.phone_number:
            return user.phone_number
        raise AuthError('PHONE_REQUIRED', 'phone_number is required.')

    @staticmethod
    def _reclaim(holder: User, phone: str, *, new_owner: User) -> None:
        """Moves an unverified number to the account that proved possession of it."""
        holder.phone_number = None
        db.session.add(AccountDataIssue(
            user_id=holder.id,
            field='phone_number',
            issue_type=AccountDataIssueType.PHONE_RECLAIMED,
            source='phone_verification',
            raw_value=phone,
            normalized_value=phone,
            conflicting_user_id=new_owner.id,
        ))
        record_audit(
            user_id=new_owner.id,
            action='RECLAIM_PHONE_NUMBER',
            entity_type='User',
            entity_id=holder.id,
            old_value={'phone_number': phone},
            new_value={'phone_number': None, 'claimed_by_user_id': new_owner.id},
            ip_address=None,
        )
        # Release the unique value before assigning it to the new owner.
        db.session.flush()

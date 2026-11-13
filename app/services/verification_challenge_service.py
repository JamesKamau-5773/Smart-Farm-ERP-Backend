"""Issues and checks one-time codes and link tokens.

This is the single place that knows how challenges are generated, hashed,
expired and attempt-limited. Purpose-specific flows (phone verification,
password recovery, email verification) build on it. Nothing here commits; the
orchestrating service owns the transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app

from app.models.auth import ChallengePurpose, VerificationChallenge
from app.models.user import User
from app.repositories.verification_challenge_repo import VerificationChallengeRepository
from app.utils.secret_hashing import (
    generate_numeric_code,
    generate_public_id,
    generate_url_token,
    hash_secret,
    secret_matches,
)

CODE_PREFIXES = {
    ChallengePurpose.PHONE_VERIFICATION: 'VERIFY',
    ChallengePurpose.PASSWORD_RESET_CODE: 'RESET',
}
PUBLIC_ID_PREFIXES = {
    ChallengePurpose.PHONE_VERIFICATION: 'pv',
    ChallengePurpose.PASSWORD_RESET_CODE: 'prc',
    ChallengePurpose.PASSWORD_RESET_LINK: 'prl',
    ChallengePurpose.EMAIL_VERIFICATION: 'ev',
}


class CodeMatchStatus:
    MATCHED = 'matched'
    MISMATCH = 'mismatch'
    NO_CHALLENGE = 'no_challenge'


@dataclass(frozen=True)
class IssuedChallenge:
    challenge: VerificationChallenge
    secret: str

    @property
    def message_text(self) -> str:
        return f'{CODE_PREFIXES[self.challenge.purpose]}-{self.secret}'


@dataclass(frozen=True)
class CodeMatch:
    status: str
    challenge: Optional[VerificationChallenge] = None


class VerificationChallengeService:
    @staticmethod
    def ttl() -> timedelta:
        return timedelta(seconds=int(current_app.config['AUTH_CHALLENGE_TTL_SECONDS']))

    @staticmethod
    def max_attempts() -> int:
        return int(current_app.config['AUTH_CHALLENGE_MAX_ATTEMPTS'])

    @staticmethod
    def generate_decoy_code(purpose: str) -> str:
        """A code in the same format as a real one, never persisted."""
        return f'{CODE_PREFIXES[purpose]}-{generate_numeric_code()}'

    @staticmethod
    def issue_code(user: User, *, purpose: str, target: str, channel: str = 'whatsapp', ip_address=None) -> IssuedChallenge:
        return VerificationChallengeService._issue(
            user, purpose=purpose, target=target, channel=channel,
            secret=generate_numeric_code(), ip_address=ip_address,
        )

    @staticmethod
    def issue_link_token(user: User, *, purpose: str, target: str, channel: str, created_by_id=None, ip_address=None) -> IssuedChallenge:
        return VerificationChallengeService._issue(
            user, purpose=purpose, target=target, channel=channel,
            secret=generate_url_token(), created_by_id=created_by_id, ip_address=ip_address,
        )

    @staticmethod
    def _issue(user, *, purpose, target, channel, secret, created_by_id=None, ip_address=None) -> IssuedChallenge:
        # Only one open challenge per user and purpose; a new request supersedes the old.
        VerificationChallengeRepository.cancel_open_for_user(user.id, [purpose])
        challenge = VerificationChallengeRepository.add(VerificationChallenge(
            public_id=generate_public_id(PUBLIC_ID_PREFIXES[purpose]),
            user_id=user.id,
            purpose=purpose,
            channel=channel,
            target=target,
            secret_hash=hash_secret(secret, purpose=purpose),
            max_attempts=VerificationChallengeService.max_attempts(),
            expires_at=datetime.now(timezone.utc) + VerificationChallengeService.ttl(),
            created_by_id=created_by_id,
            created_ip=ip_address,
        ))
        return IssuedChallenge(challenge=challenge, secret=secret)

    @staticmethod
    def match_code_from_sender(*, purpose: str, sender: str, code: str, message_id: Optional[str] = None) -> CodeMatch:
        """Reverse-OTP check: the code must belong to a pending challenge whose
        target is the sender's own number. A wrong code from a number with
        pending challenges counts as a failed attempt on each of them."""
        candidates = [
            challenge
            for challenge in VerificationChallengeRepository.list_open_for_target(purpose, sender)
            if challenge.is_pending
        ]
        if not candidates:
            return CodeMatch(CodeMatchStatus.NO_CHALLENGE)

        for challenge in candidates:
            challenge.last_inbound_message_id = message_id
            if secret_matches(code, challenge.secret_hash, purpose=purpose):
                challenge.verified_at = datetime.now(timezone.utc)
                return CodeMatch(CodeMatchStatus.MATCHED, challenge)

        for challenge in candidates:
            challenge.attempts += 1
        return CodeMatch(CodeMatchStatus.MISMATCH)

    @staticmethod
    def find_pending_by_token(*, purpose: str, token: str) -> Optional[VerificationChallenge]:
        if not token:
            return None
        challenge = VerificationChallengeRepository.get_open_by_secret_hash(
            purpose, hash_secret(token, purpose=purpose),
        )
        return challenge if challenge and challenge.is_pending else None

    @staticmethod
    def record_failed_attempt(challenge: VerificationChallenge) -> None:
        challenge.attempts += 1

    @staticmethod
    def consume(challenge: VerificationChallenge) -> None:
        now = datetime.now(timezone.utc)
        challenge.verified_at = challenge.verified_at or now
        challenge.consumed_at = now

    @staticmethod
    def cancel(challenge: VerificationChallenge) -> None:
        challenge.cancelled_at = datetime.now(timezone.utc)

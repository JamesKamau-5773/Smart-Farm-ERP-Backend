from datetime import datetime, timezone
from typing import Iterable, List, Optional

from app import db
from app.models.auth import VerificationChallenge


class VerificationChallengeRepository:
    @staticmethod
    def add(challenge: VerificationChallenge) -> VerificationChallenge:
        db.session.add(challenge)
        db.session.flush()
        return challenge

    @staticmethod
    def get_for_user(public_id: str, user_id: int) -> Optional[VerificationChallenge]:
        return VerificationChallenge.query.filter_by(public_id=public_id, user_id=user_id).first()

    @staticmethod
    def get_open_by_secret_hash(purpose: str, secret_hash: str) -> Optional[VerificationChallenge]:
        """Open = not cancelled and not consumed; expiry/attempts are checked by the caller."""
        return (
            VerificationChallenge.query
            .filter_by(purpose=purpose, secret_hash=secret_hash, cancelled_at=None, consumed_at=None)
            .with_for_update()
            .first()
        )

    @staticmethod
    def list_open_for_target(purpose: str, target: str) -> List[VerificationChallenge]:
        return (
            VerificationChallenge.query
            .filter_by(purpose=purpose, target=target, cancelled_at=None, consumed_at=None, verified_at=None)
            .with_for_update()
            .all()
        )

    @staticmethod
    def cancel_open_for_user(user_id: int, purposes: Iterable[str]) -> None:
        VerificationChallenge.query.filter(
            VerificationChallenge.user_id == user_id,
            VerificationChallenge.purpose.in_(list(purposes)),
            VerificationChallenge.cancelled_at.is_(None),
            VerificationChallenge.consumed_at.is_(None),
            VerificationChallenge.verified_at.is_(None),
        ).update({'cancelled_at': datetime.now(timezone.utc)}, synchronize_session=False)

    @staticmethod
    def message_already_processed(message_id: Optional[str]) -> bool:
        if not message_id:
            return False
        return db.session.query(
            VerificationChallenge.query.filter_by(last_inbound_message_id=message_id).exists()
        ).scalar()

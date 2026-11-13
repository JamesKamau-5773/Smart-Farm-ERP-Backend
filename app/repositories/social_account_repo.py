from typing import List, Optional

from app import db
from app.models.auth import SocialAccount


class SocialAccountRepository:
    @staticmethod
    def get(provider: str, provider_user_id: str) -> Optional[SocialAccount]:
        return SocialAccount.query.filter_by(provider=provider, provider_user_id=provider_user_id).first()

    @staticmethod
    def get_for_user(user_id: int, provider: str) -> Optional[SocialAccount]:
        return SocialAccount.query.filter_by(user_id=user_id, provider=provider).first()

    @staticmethod
    def providers_for_user(user_id: int) -> List[str]:
        rows = db.session.query(SocialAccount.provider).filter_by(user_id=user_id).order_by(SocialAccount.provider).all()
        return [provider for (provider,) in rows]

    @staticmethod
    def add(account: SocialAccount) -> SocialAccount:
        db.session.add(account)
        db.session.flush()
        return account

    @staticmethod
    def delete(account: SocialAccount) -> None:
        db.session.delete(account)

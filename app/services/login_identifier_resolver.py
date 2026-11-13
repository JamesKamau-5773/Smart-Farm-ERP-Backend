"""Maps a login identifier (phone, email or username) to a user account."""
from __future__ import annotations

import re
from typing import List, Optional

from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.utils.phone import to_wa_id, try_to_e164

_PHONE_LIKE = re.compile(r'^\+?[\d\s\-().]{7,20}$')


class LoginIdentifierResolver:
    @staticmethod
    def resolve(identifier: Optional[str]) -> Optional[User]:
        candidates = LoginIdentifierResolver.candidates(identifier)
        return candidates[0] if candidates else None

    @staticmethod
    def candidates(identifier: Optional[str]) -> List[User]:
        """Every account the identifier could refer to, most specific first.

        A phone-like value can be one account's phone number and another
        account's username (legacy rows used the phone as username), so login
        checks the password against each candidate rather than guessing.
        """
        value = (identifier or '').strip()
        if not value:
            return []
        if '@' in value:
            user = _signable(UserRepository.get_by_email_ci(value))
            return [user] if user else []

        found = []
        if _PHONE_LIKE.match(value):
            found.append(LoginIdentifierResolver.resolve_phone(value))
        found.append(_signable(UserRepository.get_by_username(value) or UserRepository.get_by_username_ci(value)))

        unique = []
        for user in found:
            if user and user not in unique:
                unique.append(user)
        return unique

    @staticmethod
    def resolve_phone(value: str) -> Optional[User]:
        e164 = try_to_e164(value)
        if not e164:
            return None
        user = UserRepository.get_by_phone(e164)
        if user:
            return _signable(user)
        # Accounts whose phone was never copied into phone_number.
        digits = to_wa_id(e164)
        national = '0' + digits[3:] if digits.startswith('254') else None
        return _signable(UserRepository.find_by_legacy_phone({value, digits, national}))


def _signable(user: Optional[User]) -> Optional[User]:
    """Demo accounts are reachable only through POST /api/auth/demo, never by
    login, recovery or any other identifier lookup."""
    return None if user is None or user.is_demo else user

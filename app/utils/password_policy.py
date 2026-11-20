"""Password policy applied wherever a new password is set (never at login)."""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from app.utils.auth_errors import WeakPasswordError


class PasswordPolicy:
    MIN_LENGTH = 8
    MAX_LENGTH = 128
    MIN_PERSONAL_FRAGMENT = 4
    COMMON_PASSWORDS = frozenset({
        'password', 'password1', 'password12', 'password123', 'passw0rd', 'p@ssw0rd',
        '12345678', '123456789', '1234567890', 'qwerty123', 'qwertyuiop', 'abc12345',
        'iloveyou1', 'welcome1', 'welcome123', 'admin123', 'letmein1', 'changeme1',
        'kenya2024', 'kenya2025', 'kenya2026', 'nairobi1', 'nairobi123', 'maziwa123',
        'farmer123', 'dairy1234', 'jivu12345', 'test1234', 'monkey123', 'football1',
    })

    @classmethod
    def violations(cls, password: Optional[str], *, personal_values: Iterable[Optional[str]] = ()) -> List[str]:
        password = password or ''
        found = []
        if len(password) < cls.MIN_LENGTH:
            found.append('min_length')
        if len(password) > cls.MAX_LENGTH:
            found.append('max_length')
        if not (re.search(r'[A-Za-z]', password) and re.search(r'\d', password)):
            found.append('letter_and_digit')
        if cls._contains_personal_value(password, personal_values):
            found.append('not_personal')
        if password.lower() in cls.COMMON_PASSWORDS:
            found.append('not_common')
        return found

    @classmethod
    def enforce(cls, password: Optional[str], *, personal_values: Iterable[Optional[str]] = ()) -> None:
        found = cls.violations(password, personal_values=personal_values)
        if found:
            raise WeakPasswordError(found)

    @classmethod
    def personal_values_for(cls, user) -> List[Optional[str]]:
        email = getattr(user, 'email', None) or ''
        return [
            getattr(user, 'username', None),
            getattr(user, 'phone_number', None),
            email.split('@', 1)[0] if email else None,
        ]

    @classmethod
    def _contains_personal_value(cls, password: str, personal_values: Iterable[Optional[str]]) -> bool:
        lowered = password.lower()
        password_digits = re.sub(r'\D', '', password)
        for value in personal_values:
            value = (value or '').strip().lower()
            if not value:
                continue
            value_digits = re.sub(r'\D', '', value)
            if len(value_digits) >= 9 and re.fullmatch(r'\+?[\d\s\-]+', value):
                # Phone-like: compare the subscriber part (last 9 digits).
                if value_digits[-9:] in password_digits:
                    return True
                continue
            if len(value) >= cls.MIN_PERSONAL_FRAGMENT and value in lowered:
                return True
        return False

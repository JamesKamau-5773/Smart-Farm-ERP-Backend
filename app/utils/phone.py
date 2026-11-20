"""Phone number normalisation.

User phone numbers are stored in E.164 (``+254712345678``). WhatsApp identifies
senders by the same number without the leading ``+`` (its ``wa_id``), so
``to_wa_id``/``from_wa_id`` convert between the two representations.
"""
from __future__ import annotations

import re
from typing import Optional

import phonenumbers

DEFAULT_REGION = 'KE'
_PHONE_CHARACTERS = re.compile(r'^\+?[\d\s\-().]+$')


class InvalidPhoneNumber(ValueError):
    """Raised when a value cannot be parsed into a valid phone number."""


def _digits(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def to_e164(value: Optional[str], region: str = DEFAULT_REGION) -> str:
    """Normalise a phone number to E.164.

    Accepts local (``0712…``, ``0112…``), short (``712…``), country-code
    (``254712…``) and international (``+254712…``) forms.
    """
    raw = (value or '').strip()
    if not raw or not _PHONE_CHARACTERS.match(raw):
        raise InvalidPhoneNumber('phone_number must be a valid phone number.')

    digits = _digits(raw)
    if raw.startswith('+') or raw.startswith('00'):
        candidate = '+' + (digits[2:] if raw.startswith('00') else digits)
    else:
        candidate = digits

    try:
        parsed = phonenumbers.parse(candidate, region)
    except phonenumbers.NumberParseException as error:
        raise InvalidPhoneNumber('phone_number must be a valid phone number.') from error

    if not phonenumbers.is_valid_number(parsed):
        # Country-code form without '+' (e.g. WhatsApp wa_id '447911123456').
        if not raw.startswith('+'):
            try:
                parsed = phonenumbers.parse('+' + digits, None)
            except phonenumbers.NumberParseException as error:
                raise InvalidPhoneNumber('phone_number must be a valid phone number.') from error
        if not phonenumbers.is_valid_number(parsed):
            raise InvalidPhoneNumber('phone_number must be a valid phone number.')

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def try_to_e164(value: Optional[str], region: str = DEFAULT_REGION) -> Optional[str]:
    try:
        return to_e164(value, region)
    except InvalidPhoneNumber:
        return None


def to_wa_id(e164: str) -> str:
    """WhatsApp's digits-only form of an E.164 number."""
    return _digits(e164)


def from_wa_id(wa_id: Optional[str]) -> Optional[str]:
    digits = _digits(wa_id or '')
    return try_to_e164(f'+{digits}') if digits else None


def phone_identifier(e164: str) -> str:
    """Stable ``users.identifier`` value for phone-based accounts."""
    return f'phone_{to_wa_id(e164)}'


def phone_username(e164: str) -> str:
    """Default username for phone-based accounts (digits only, so it satisfies
    the claim-account username rules)."""
    return to_wa_id(e164)

"""Encryption at rest for secrets the app must read back (TOTP secrets).

Keys come from MFA_ENCRYPTION_KEYS: comma-separated Fernet keys, newest first.
New values are encrypted with the first; any listed key decrypts, so a key can
be rotated by putting the new one in front and dropping the old one later.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from flask import current_app


class SecretCipherNotConfigured(RuntimeError):
    """MFA_ENCRYPTION_KEYS is missing or invalid."""


class SecretCipherError(ValueError):
    """A stored value could not be decrypted with any configured key."""


def _keys() -> list:
    raw = current_app.config.get('MFA_ENCRYPTION_KEYS') or ''
    return [key.strip() for key in raw.split(',') if key.strip()]


def _cipher() -> MultiFernet:
    keys = _keys()
    if not keys:
        raise SecretCipherNotConfigured('MFA_ENCRYPTION_KEYS is not set.')
    try:
        return MultiFernet([Fernet(key.encode('ascii')) for key in keys])
    except (ValueError, TypeError) as error:
        raise SecretCipherNotConfigured('MFA_ENCRYPTION_KEYS holds an invalid Fernet key.') from error


def is_configured() -> bool:
    try:
        _cipher()
    except SecretCipherNotConfigured:
        return False
    return True


def encrypt(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode('utf-8')).decode('ascii')


def decrypt(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode('ascii')).decode('utf-8')
    except InvalidToken as error:
        raise SecretCipherError('The stored secret cannot be decrypted with the configured keys.') from error

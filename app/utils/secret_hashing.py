"""Generation and keyed hashing of one-time codes and tokens.

Only HMAC-SHA256 digests are persisted. The key (``AUTH_CODE_PEPPER``) lives
outside the database, so a leaked table cannot be brute-forced offline even for
short numeric codes.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from flask import current_app


def generate_numeric_code(digits: int = 6) -> str:
    return f'{secrets.randbelow(10 ** digits):0{digits}d}'


def generate_url_token() -> str:
    return secrets.token_urlsafe(32)


def generate_public_id(prefix: str) -> str:
    return f'{prefix}_{secrets.token_urlsafe(12)}'


def hash_secret(secret: str, *, purpose: str) -> str:
    key = current_app.config['AUTH_CODE_PEPPER'].encode('utf-8')
    message = f'{purpose}:{secret}'.encode('utf-8')
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def secret_matches(secret: str, expected_hash: str, *, purpose: str) -> bool:
    return hmac.compare_digest(hash_secret(secret, purpose=purpose), expected_hash or '')

"""User-facing copy for authentication emails and WhatsApp replies."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from flask import current_app

from app.services.email_sender import EmailMessage


def frontend_url(path: str) -> str:
    return f"{current_app.config['FRONTEND_BASE_URL'].rstrip('/')}{path}"


def reset_password_url(token: str) -> str:
    return frontend_url(f'/reset-password?token={quote(token)}')


def verify_email_url(token: str) -> str:
    return frontend_url(f'/verify-email?token={quote(token)}')


def whatsapp_business_number() -> str:
    return current_app.config.get('WHATSAPP_BUSINESS_NUMBER') or ''


def wa_link(message_text: str) -> str:
    digits = ''.join(ch for ch in whatsapp_business_number() if ch.isdigit())
    return f'https://wa.me/{digits}?text={quote(message_text)}'


def _minutes(seconds: int) -> int:
    return max(int(seconds) // 60, 1)


def password_reset_email(to: str, url: str, expires_in_seconds: int) -> EmailMessage:
    minutes = _minutes(expires_in_seconds)
    return EmailMessage(
        to=to,
        subject='Reset your Maziwa Smart password',
        text=(
            f'We received a request to reset your password.\n\n'
            f'Open this link within {minutes} minutes to choose a new password:\n{url}\n\n'
            f'If you did not ask for this, you can ignore this email.'
        ),
        html=(
            f'<p>We received a request to reset your password.</p>'
            f'<p><a href="{escape(url)}">Choose a new password</a> (valid for {minutes} minutes).</p>'
            f'<p>If you did not ask for this, you can ignore this email.</p>'
        ),
    )


def email_verification_email(to: str, url: str, expires_in_seconds: int) -> EmailMessage:
    minutes = _minutes(expires_in_seconds)
    return EmailMessage(
        to=to,
        subject='Confirm your email for Maziwa Smart',
        text=f'Confirm your email address within {minutes} minutes:\n{url}',
        html=f'<p><a href="{escape(url)}">Confirm your email address</a> (valid for {minutes} minutes).</p>',
    )


WHATSAPP_PHONE_VERIFIED = '✅ Your phone number is verified. You can return to the app.'
WHATSAPP_PHONE_TAKEN = 'This number is already verified on another account. Please contact support.'
WHATSAPP_CODE_INVALID = 'That code is invalid or has expired. Please request a new one in the app.'


def whatsapp_reset_link_reply(url: str, expires_in_seconds: int) -> str:
    return (
        f'Open this link within {_minutes(expires_in_seconds)} minutes to reset your password:\n{url}\n\n'
        f'If you did not request this, ignore this message.'
    )

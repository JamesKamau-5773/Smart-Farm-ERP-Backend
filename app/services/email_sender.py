"""Transactional email delivery.

``EmailSender`` is the port; ``ResendEmailSender`` is the production adapter.
``dispatch_email`` hands delivery to Celery when enabled so request latency does
not reveal whether an email was actually sent (account enumeration).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Protocol

import requests
from flask import current_app

log = logging.getLogger(__name__)

RESEND_API_URL = 'https://api.resend.com/emails'


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str


class EmailDeliveryError(RuntimeError):
    pass


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class ResendEmailSender:
    def __init__(self, api_key: str, from_address: str, timeout: int = 10):
        self._api_key = api_key
        self._from_address = from_address
        self._timeout = timeout

    def send(self, message: EmailMessage) -> None:
        try:
            response = requests.post(
                RESEND_API_URL,
                json={
                    'from': self._from_address,
                    'to': [message.to],
                    'subject': message.subject,
                    'html': message.html,
                    'text': message.text,
                },
                headers={'Authorization': f'Bearer {self._api_key}'},
                timeout=self._timeout,
            )
        except requests.RequestException as error:
            raise EmailDeliveryError('Email provider is unreachable.') from error
        if response.status_code >= 400:
            raise EmailDeliveryError(f'Email provider rejected the message (HTTP {response.status_code}).')


def email_delivery_enabled() -> bool:
    return bool(current_app.config.get('RESEND_API_KEY') and current_app.config.get('EMAIL_FROM'))


def get_email_sender() -> EmailSender:
    return ResendEmailSender(current_app.config['RESEND_API_KEY'], current_app.config['EMAIL_FROM'])


def deliver_email(message: EmailMessage) -> None:
    """Synchronous, best-effort delivery. Failures are logged, never raised to the client."""
    if not email_delivery_enabled():
        log.warning('Email delivery is not configured; dropping message with subject %r.', message.subject)
        return
    try:
        get_email_sender().send(message)
    except EmailDeliveryError:
        log.exception('Failed to deliver email with subject %r.', message.subject)


def dispatch_email(message: EmailMessage) -> None:
    if current_app.config.get('AUTH_EMAIL_ASYNC'):
        try:
            from app.tasks.notification_tasks import send_email_task
            send_email_task.delay(asdict(message))
            return
        except Exception:
            log.exception('Could not enqueue email; delivering synchronously.')
    deliver_email(message)

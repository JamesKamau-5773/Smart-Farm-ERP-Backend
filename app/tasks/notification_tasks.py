from __future__ import annotations

from app import celery as celery_app
from app.services.email_sender import EmailMessage, deliver_email


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def send_email_task(self, message: dict) -> None:
    deliver_email(EmailMessage(**message))

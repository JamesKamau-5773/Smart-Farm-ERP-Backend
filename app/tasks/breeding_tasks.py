from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from app import celery as celery_app
from app import db
from app.models.livestock import BreedingLog
from app.models.user import User

log = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_pregnancy_check_reminder(self, tenant_id: int, cow_id: int, breeding_log_id: int) -> dict:
    """Send a reminder to review pregnancy status after 21 days of AI service."""
    try:
        breeding_log = db.session.get(BreedingLog, breeding_log_id)
        if breeding_log is None or breeding_log.tenant_id != tenant_id or breeding_log.cow_id != cow_id:
            return {"status": "skipped", "reason": "breeding_log_not_found_or_mismatch"}

        user = db.session.query(User).filter_by(tenant_id=tenant_id).order_by(User.id.asc()).first()
        reminder_payload = {
            "tenant_id": tenant_id,
            "cow_id": cow_id,
            "breeding_log_id": breeding_log_id,
            "message": "Pregnancy check due: review this cow for heat return or pregnancy confirmation.",
            "owner_contact": user.email if user else None,
        }
        log.info("Pregnancy check reminder queued: %s", reminder_payload)
        return {"status": "queued", "reminder": reminder_payload}
    except Exception as exc:
        log.exception("Failed to send pregnancy check reminder for breeding_log_id=%s", breeding_log_id)
        raise self.retry(exc=exc)


def schedule_pregnancy_check_reminder(*, tenant_id: int, cow_id: int, breeding_log_id: int, insemination_date: date) -> None:
    """Schedule the reminder 21 days after the insemination date.

    Best-effort side effect: a broker/Celery outage must never fail the
    insemination write that already committed, so dispatch errors are logged
    and swallowed here rather than propagated to the caller.
    """
    reminder_date = insemination_date + timedelta(days=21)
    reminder_datetime = datetime.combine(reminder_date, datetime.min.time(), tzinfo=timezone.utc)

    eta = reminder_datetime
    try:
        send_pregnancy_check_reminder.apply_async(args=[tenant_id, cow_id, breeding_log_id], eta=eta)
    except Exception:
        log.exception(
            "Failed to schedule pregnancy check reminder for breeding_log_id=%s (tenant_id=%s, cow_id=%s)",
            breeding_log_id, tenant_id, cow_id,
        )

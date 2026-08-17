from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app

from app import db
from app.models.livestock import AnimalTimelineEvent


class AnimalTimelineService:
    """Fans clinical/breeding writes out into the animal passport timeline.

    Medical and breeding records live in their own tables (medical_records,
    vet_visits, breeding_logs). The Animal Passport page only reads from
    animal_events, so every write path that creates a clinical or breeding
    record must also mirror a row here or the passport silently goes stale.
    """

    @staticmethod
    def record_event(
        *,
        tenant_id: int,
        cow_id: int,
        event_type: str,
        title: str,
        description: str | None = None,
        event_date=None,
        event_data: dict | None = None,
        created_by=None,
    ) -> AnimalTimelineEvent | None:
        if tenant_id is None or cow_id is None:
            return None

        if isinstance(created_by, str):
            try:
                created_by = int(created_by)
            except (TypeError, ValueError):
                created_by = None

        resolved_date = event_date
        if resolved_date is not None and not isinstance(resolved_date, datetime):
            resolved_date = datetime.combine(resolved_date, datetime.min.time())
        if resolved_date is not None and resolved_date.tzinfo is None:
            resolved_date = resolved_date.replace(tzinfo=timezone.utc)
        if resolved_date is None:
            resolved_date = datetime.now(timezone.utc)

        try:
            event = AnimalTimelineEvent(
                tenant_id=tenant_id,
                cow_id=cow_id,
                event_type=event_type,
                title=title,
                description=description,
                event_date=resolved_date,
                event_data=event_data or {},
                created_by=created_by,
            )
            db.session.add(event)
            db.session.commit()
            return event
        except Exception:
            # The timeline mirror is best-effort: never let it break the
            # primary medical/breeding write that already succeeded.
            db.session.rollback()
            current_app.logger.exception(
                "Failed to mirror event_type=%s for cow_id=%s into animal_events", event_type, cow_id
            )
            return None

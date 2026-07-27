"""
Celery tasks for genetic scoring.

This module defines the *contract* for when reliability recalculation fires.
The trigger is explicit: LactationService (or any future service that closes a
lactation cycle) calls recalculate_genetic_reliability.delay(...) after committing
its own transaction. The task failure never affects the caller's transaction.
"""

from __future__ import annotations

import logging

from app import celery as celery_app
from app.services.genetic_reliability_service import GeneticReliabilityService

log = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def recalculate_genetic_reliability(self, cow_id: int, tenant_id: int) -> dict:
    """
    Async task: recalculate genetic trait score reliability for a cow.

    Dispatched after a lactation cycle is closed. Retries up to 3 times
    on transient failures (e.g. DB connection blip) with a 60-second delay.

    Args:
        cow_id:    DB id of the cow whose reliability needs updating.
        tenant_id: Tenant context.

    Returns:
        Dict with cow_id and the new reliability percentage.
    """
    try:
        new_reliability = GeneticReliabilityService.recalculate(cow_id, tenant_id)
        return {'cow_id': cow_id, 'reliability': new_reliability}
    except Exception as exc:
        log.exception(
            "Failed to recalculate genetic reliability for cow_id=%d (attempt %d/%d)",
            cow_id,
            self.request.retries + 1,
            self.max_retries + 1,
        )
        raise self.retry(exc=exc)

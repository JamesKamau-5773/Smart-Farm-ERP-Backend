"""
GeneticReliabilityService — SRP: recalculates the confidence (reliability %) on
a cow's genetic trait scores based on her observed performance history.

The sole input is completed lactation cycle count. The output is an updated
reliability integer written to every GeneticTraitScore row for that animal.

Nothing else should be done in this service.
"""

from __future__ import annotations

import logging

from app import db
from app.repositories.genetic_repo import GeneticRepository

log = logging.getLogger(__name__)

# Reliability tiers, keyed by minimum number of completed lactations.
_RELIABILITY_TIERS: list[tuple[int, int]] = [
    (3, 90),
    (2, 75),
    (1, 60),
    (0, 50),  # baseline — projected but no observed performance yet
]


def _reliability_for_lactation_count(count: int) -> int:
    for min_lactations, reliability in _RELIABILITY_TIERS:
        if count >= min_lactations:
            return reliability
    return 50


class GeneticReliabilityService:

    @staticmethod
    def recalculate(cow_id: int, tenant_id: int) -> int:
        """
        Recalculate and persist the reliability percentage for all of a cow's
        genetic trait scores.

        This is the single implementation called by both:
          - the Celery task (async, post-lactation-close)
          - the manual recalculation API endpoint (explicit override)

        Args:
            cow_id:    The cow whose scores need updating.
            tenant_id: Tenant context for profile lookup.

        Returns:
            The new reliability percentage (0–100).
        """
        profile = GeneticRepository.get_profile_by_cow(cow_id, tenant_id)
        if not profile:
            log.info(
                "No genetic profile for cow_id=%d tenant_id=%d; skipping reliability update.",
                cow_id,
                tenant_id,
            )
            return 50

        completed_cycles = GeneticRepository.count_completed_lactation_cycles(cow_id)
        new_reliability = _reliability_for_lactation_count(completed_cycles)

        GeneticRepository.update_reliability_for_profile(profile.id, new_reliability)
        db.session.commit()

        log.info(
            "Updated reliability to %d%% for cow_id=%d (completed cycles: %d)",
            new_reliability,
            cow_id,
            completed_cycles,
        )
        return new_reliability

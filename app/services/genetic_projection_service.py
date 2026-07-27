"""
GeneticProjectionService — SRP: calculates projected genetic trait scores for a calf.

Called once when a calf is registered in the system. It reads the dam's (mother's)
existing trait scores and the sire's PTA values provided by the user, averages them,
and persists the result with a baseline reliability of 50%.

Nothing else should be done in this service.
"""

from __future__ import annotations

import logging
from typing import Any

from app import db
from app.models.genetics import GeneticProfile, GeneticTraitScore
from app.repositories.genetic_repo import GeneticRepository

log = logging.getLogger(__name__)

# Reliability assigned to all system-projected (calf) scores at birth.
PROJECTED_RELIABILITY = 50


class GeneticProjectionService:

    @staticmethod
    def project_calf_scores(
        calf_cow_id: int,
        dam_cow_id: int,
        sire_pta_scores: dict[str, float],
        tenant_id: int,
    ) -> GeneticProfile:
        """
        Calculate and persist preliminary genetic trait scores for a newborn calf.

        The score for each trait is the average of:
          - the dam's recorded trait value (from GeneticTraitScore)
          - the sire's PTA value provided by the user at breeding time

        Traits present in the dam but missing from sire_pta_scores (and vice versa)
        are skipped — we only project where both parents have data.

        Args:
            calf_cow_id:    The DB id of the newly registered calf.
            dam_cow_id:     The DB id of the dam (mother).
            sire_pta_scores: Dict mapping trait name -> PTA float value, sourced
                             from the semen catalog entry at breeding time.
                             e.g. {"milk_volume": 320.5, "fat_percentage": 0.12}
            tenant_id:      Tenant context.

        Returns:
            The newly created GeneticProfile for the calf.

        Raises:
            ValueError: If the dam has no genetic profile.
        """
        dam_profile = GeneticRepository.get_profile_by_cow(dam_cow_id, tenant_id)
        if not dam_profile:
            raise ValueError(
                f"Dam (cow_id={dam_cow_id}) has no genetic profile. "
                "Cannot project calf scores without baseline dam data."
            )

        dam_scores: dict[str, Any] = {
            ts.trait_definition.name: float(ts.value)
            for ts in dam_profile.trait_scores
            if ts.trait_definition is not None
        }

        traits_to_project = set(dam_scores.keys()) & set(sire_pta_scores.keys())
        if not traits_to_project:
            raise ValueError(
                "No overlapping traits between dam profile and sire PTA scores. "
                "Ensure sire PTA keys match trait definition names."
            )

        calf_profile = GeneticRepository.get_or_create_profile(
            cow_id=calf_cow_id,
            tenant_id=tenant_id,
            source=GeneticProfile.SOURCE_PROJECTED,
        )

        for trait_name in traits_to_project:
            trait_def = GeneticRepository.get_trait_definition_by_name(trait_name)
            if trait_def is None:
                log.warning("Trait definition '%s' not found in lookup table; skipping.", trait_name)
                continue

            projected_value = (dam_scores[trait_name] + sire_pta_scores[trait_name]) / 2.0

            GeneticRepository.upsert_trait_score(
                profile_id=calf_profile.id,
                trait_definition_id=trait_def.id,
                value=projected_value,
                reliability=PROJECTED_RELIABILITY,
                scored_source=GeneticTraitScore.SCORED_SOURCE_SYSTEM,
            )

        db.session.commit()
        log.info(
            "Projected %d trait scores for calf cow_id=%d (dam=%d)",
            len(traits_to_project),
            calf_cow_id,
            dam_cow_id,
        )
        return calf_profile

"""
Repository for genetic profile and trait score data access.
Follows SRP: only persistence and query logic here.
"""

from __future__ import annotations

from typing import Optional

from app import db
from app.models.genetics import GeneticProfile, GeneticTraitDefinition, GeneticTraitScore
from app.models.livestock import LactationCycle


class GeneticRepository:

    # ------------------------------------------------------------------
    # GeneticProfile
    # ------------------------------------------------------------------

    @staticmethod
    def get_profile_by_cow(cow_id: int, tenant_id: int) -> Optional[GeneticProfile]:
        return GeneticProfile.query.filter_by(cow_id=cow_id, tenant_id=tenant_id).first()

    @staticmethod
    def get_or_create_profile(cow_id: int, tenant_id: int, source: str) -> GeneticProfile:
        profile = GeneticRepository.get_profile_by_cow(cow_id, tenant_id)
        if not profile:
            profile = GeneticProfile(cow_id=cow_id, tenant_id=tenant_id, source=source)
            db.session.add(profile)
            db.session.flush()  # populate profile.id without committing
        return profile

    # ------------------------------------------------------------------
    # GeneticTraitDefinition
    # ------------------------------------------------------------------

    @staticmethod
    def get_all_trait_definitions() -> list[GeneticTraitDefinition]:
        return GeneticTraitDefinition.query.order_by(GeneticTraitDefinition.category, GeneticTraitDefinition.name).all()

    @staticmethod
    def get_trait_definition_by_name(name: str) -> Optional[GeneticTraitDefinition]:
        return GeneticTraitDefinition.query.filter_by(name=name).first()

    # ------------------------------------------------------------------
    # GeneticTraitScore
    # ------------------------------------------------------------------

    @staticmethod
    def upsert_trait_score(
        profile_id: int,
        trait_definition_id: int,
        value: float,
        reliability: int,
        scored_source: str,
    ) -> GeneticTraitScore:
        score = GeneticTraitScore.query.filter_by(
            profile_id=profile_id,
            trait_definition_id=trait_definition_id,
        ).first()

        if score:
            score.value = value
            score.reliability = reliability
            score.scored_source = scored_source
        else:
            score = GeneticTraitScore(
                profile_id=profile_id,
                trait_definition_id=trait_definition_id,
                value=value,
                reliability=reliability,
                scored_source=scored_source,
            )
            db.session.add(score)

        return score

    @staticmethod
    def update_reliability_for_profile(profile_id: int, reliability: int) -> None:
        """Bulk-update the reliability on all trait scores for a profile."""
        GeneticTraitScore.query.filter_by(profile_id=profile_id).update(
            {'reliability': reliability},
            synchronize_session=False,
        )

    # ------------------------------------------------------------------
    # Lactation history (read-only; source of truth for reliability)
    # ------------------------------------------------------------------

    @staticmethod
    def count_completed_lactation_cycles(cow_id: int) -> int:
        """
        A completed cycle has an actual_calving_date and is no longer active.
        This count drives the reliability tier calculation.
        """
        return (
            LactationCycle.query
            .filter_by(cow_id=cow_id, is_active=False)
            .filter(LactationCycle.actual_calving_date.isnot(None))
            .count()
        )

"""Persistence operations for direct animal cost allocations."""

from __future__ import annotations

from app import db
from app.models.finance import AnimalCostAllocation
from app.models.livestock import Cow


class AnimalCostAllocationRepository:
    """Owns data access for animal-attributable ledger costs."""

    @staticmethod
    def get_cow(*, tenant_id: int, cow_id: int) -> Cow | None:
        return Cow.query.filter_by(id=cow_id, tenant_id=tenant_id).first()

    @staticmethod
    def list_cows(*, tenant_id: int, cow_ids: list[int]) -> list[Cow]:
        if not cow_ids:
            return []
        return Cow.query.filter(Cow.tenant_id == tenant_id, Cow.id.in_(cow_ids)).all()

    @staticmethod
    def add(allocation: AnimalCostAllocation) -> AnimalCostAllocation:
        db.session.add(allocation)
        return allocation

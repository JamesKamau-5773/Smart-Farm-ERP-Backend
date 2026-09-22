"""Application service for assigning posted expenses to individual animals."""

from __future__ import annotations

from app.models.finance import AnimalCostAllocation, AnimalCostType, Transaction, TransactionType
from app.repositories.animal_cost_allocation_repo import AnimalCostAllocationRepository


class AnimalCostAllocationService:
    """Validates and creates direct allocations without owning HTTP or persistence."""

    def __init__(self, repository: AnimalCostAllocationRepository | None = None):
        self.repository = repository or AnimalCostAllocationRepository()

    def create_for_transaction(
        self,
        *,
        tenant_id: int,
        cow_id: int,
        cost_type: str,
        transaction: Transaction,
    ) -> AnimalCostAllocation:
        if transaction.tenant_id != tenant_id:
            raise ValueError('Transaction does not belong to this tenant.')
        if transaction.transaction_type != TransactionType.EXPENSE:
            raise ValueError('Only expense transactions can be allocated to an animal.')
        cow = self.repository.get_cow(tenant_id=tenant_id, cow_id=cow_id)
        if cow is None:
            raise ValueError('Animal not found.')
        try:
            parsed_cost_type = AnimalCostType(cost_type)
        except (TypeError, ValueError) as exc:
            allowed = ', '.join(cost_type.value for cost_type in AnimalCostType)
            raise ValueError(f'animal_cost_type must be one of: {allowed}.') from exc

        return self.repository.add(AnimalCostAllocation(
            tenant_id=tenant_id,
            cow_id=cow.id,
            transaction_id=transaction.id,
            cost_type=parsed_cost_type,
            amount=transaction.amount,
            occurred_on=transaction.timestamp.date(),
            attribution_method='DIRECT',
        ))

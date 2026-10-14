"""Application service for assigning posted expenses to individual animals."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.models.finance import AnimalCostAllocation, AnimalCostType, Transaction, TransactionType
from app.repositories.animal_cost_allocation_repo import AnimalCostAllocationRepository


class AnimalCostAllocationService:
    """Validates and creates direct allocations without owning HTTP or persistence."""

    def __init__(self, repository: AnimalCostAllocationRepository | None = None):
        self.repository = repository or AnimalCostAllocationRepository()

    @staticmethod
    def _parse_cost_type(cost_type: str) -> AnimalCostType:
        try:
            return AnimalCostType(cost_type)
        except (TypeError, ValueError) as exc:
            allowed = ', '.join(item.value for item in AnimalCostType)
            raise ValueError(f'animal_cost_type must be one of: {allowed}.') from exc

    @staticmethod
    def _split_amounts(amount: Decimal, cow_count: int) -> list[Decimal]:
        cents = int((amount * Decimal('100')).to_integral_value(ROUND_HALF_UP))
        base_cents, remainder = divmod(cents, cow_count)
        amounts = [Decimal(base_cents) / Decimal('100') for _ in range(cow_count)]
        for index in range(remainder):
            amounts[index] += Decimal('0.01')
        return amounts

    def create_for_transaction(
        self,
        *,
        tenant_id: int,
        cow_ids: list[int],
        cost_type: str,
        transaction: Transaction,
    ) -> list[AnimalCostAllocation]:
        if transaction.tenant_id != tenant_id:
            raise ValueError('Transaction does not belong to this tenant.')
        if transaction.transaction_type != TransactionType.EXPENSE:
            raise ValueError('Only expense transactions can be allocated to an animal.')
        if not cow_ids:
            raise ValueError('At least one cow must be selected.')

        unique_cow_ids = list(dict.fromkeys(cow_ids))
        valid_cows = self.repository.list_cows(tenant_id=tenant_id, cow_ids=unique_cow_ids)
        valid_ids = {cow.id for cow in valid_cows}
        missing_ids = [cow_id for cow_id in unique_cow_ids if cow_id not in valid_ids]
        if missing_ids:
            raise ValueError(f'Animal not found: {missing_ids[0]}')

        parsed_cost_type = self._parse_cost_type(cost_type)
        allocation_amounts = self._split_amounts(transaction.amount, len(unique_cow_ids))
        allocations = []
        for cow_id, amount in zip(unique_cow_ids, allocation_amounts):
            allocation = AnimalCostAllocation(
                tenant_id=tenant_id,
                cow_id=cow_id,
                transaction_id=transaction.id,
                cost_type=parsed_cost_type,
                amount=amount,
                occurred_on=transaction.timestamp.date(),
                attribution_method='DIRECT',
            )
            self.repository.add(allocation)
            allocations.append(allocation)
        return allocations

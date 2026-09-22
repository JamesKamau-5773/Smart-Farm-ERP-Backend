"""Business calculations for animal lifecycle economics."""

from __future__ import annotations

from collections import defaultdict

from app.repositories.animal_economics_repo import AnimalEconomicsRepository


class AnimalEconomicsService:
    """Calculates animal rearing cost and lifetime milk contribution."""

    def __init__(self, repository: AnimalEconomicsRepository | None = None):
        self.repository = repository or AnimalEconomicsRepository()

    def get_animal_economics(self, *, tenant_id: int, cow_id: int) -> dict:
        cow = self.repository.get_cow(tenant_id=tenant_id, cow_id=cow_id)
        if cow is None:
            raise LookupError('Animal not found.')

        first_calving_date = self.repository.get_first_calving_date(cow_id=cow_id)
        allocations = self.repository.list_cost_allocations(tenant_id=tenant_id, cow_id=cow_id)
        pre_calving_cost = 0.0
        post_calving_cost = 0.0
        costs_by_type = defaultdict(float)
        for allocation in allocations:
            amount = float(allocation.amount)
            costs_by_type[allocation.cost_type.value] += amount
            if first_calving_date is None or allocation.occurred_on < first_calving_date:
                pre_calving_cost += amount
            else:
                post_calving_cost += amount

        animal_milk_by_day = self.repository.get_saleable_milk_by_day(tenant_id=tenant_id, cow_id=cow_id)
        days = list(animal_milk_by_day)
        herd_milk_by_day = self.repository.get_herd_saleable_milk_by_day(tenant_id=tenant_id, days=days)
        milk_sales_by_day = self.repository.get_milk_sales_revenue_by_day(tenant_id=tenant_id, days=days)

        allocated_revenue = 0.0
        unpriced_liters = 0.0
        for day, animal_liters in animal_milk_by_day.items():
            herd_liters = herd_milk_by_day.get(day, 0.0)
            sales_revenue = milk_sales_by_day.get(day, 0.0)
            if herd_liters > 0 and sales_revenue > 0:
                allocated_revenue += sales_revenue * (animal_liters / herd_liters)
            else:
                unpriced_liters += animal_liters

        total_saleable_liters = sum(animal_milk_by_day.values())
        attribution_quality = 'EXACT' if total_saleable_liters == 0 else ('ALLOCATED' if unpriced_liters == 0 else 'INCOMPLETE')
        return {
            'animal': {
                'id': cow.id,
                'tag_number': cow.tag_number,
                'name': cow.name,
                'date_of_birth': cow.date_of_birth.isoformat() if cow.date_of_birth else None,
                'first_calving_date': first_calving_date.isoformat() if first_calving_date else None,
            },
            'rearing_cost': {
                'amount_kes': round(pre_calving_cost, 2),
                'costs_recorded': len(allocations),
                'definition': 'Directly attributed costs before first calving.',
            },
            'lifetime_milk_contribution': {
                'saleable_milk_liters': round(total_saleable_liters, 2),
                'allocated_milk_revenue_kes': round(allocated_revenue, 2),
                'post_calving_cost_kes': round(post_calving_cost, 2),
                'amount_kes': round(allocated_revenue - post_calving_cost, 2),
            },
            'lifetime_net_contribution_kes': round(allocated_revenue - post_calving_cost - pre_calving_cost, 2),
            'costs_by_type_kes': {cost_type: round(amount, 2) for cost_type, amount in costs_by_type.items()},
            'data_quality': {
                'attribution_quality': attribution_quality,
                'cost_attribution': 'direct_ledger_allocation',
                'milk_revenue_attribution': 'daily_saleable_milk_share',
                'unpriced_saleable_liters': round(unpriced_liters, 2),
                'first_calving_recorded': first_calving_date is not None,
            },
        }

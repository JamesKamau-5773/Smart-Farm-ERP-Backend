"""How much of a mix to make, from the herd's daily demand for it."""
from __future__ import annotations

import math
from collections import defaultdict

from app.repositories.supply_repo import InventoryRepository
from app.services.feed_mixer_policy_service import FeedMixerPolicyService
from app.services.feeding_instruction_service import FeedingInstructionService
from app.services.group_feeding_plan_service import GroupFeedingPlanService

DEFAULT_DAYS = 7
MAX_DAYS = 60
ROUND_TO_KG = 5


class BatchSizingService:
    @staticmethod
    def suggest(tenant_id: int, *, recipe_type, days=DEFAULT_DAYS) -> dict:
        normalized_type = FeedMixerPolicyService.normalize_recipe_type(recipe_type, default=None)
        if normalized_type is None:
            raise ValueError('recipe_type must be one of: dairy_meal, main_meal.')
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise ValueError('days must be a whole number.')
        if not 1 <= days <= MAX_DAYS:
            raise ValueError(f'days must be between 1 and {MAX_DAYS}.')

        plan = GroupFeedingPlanService.calculate_plan_by_group(tenant_id)
        recipe = BatchSizingService._recipe_to_mix(plan['groups'], normalized_type)
        capacity = BatchSizingService._stock_capacity(tenant_id, recipe)
        groups = [
            {'feeding_group': row['feeding_group'], 'daily_kg': row['daily_group_batch_kg']}
            for row in plan['groups']
            if (row.get('assigned_recipe') or {}).get('recipe_type') == normalized_type
            and not row.get('requires_concentrate_rate')
        ]
        daily_demand = sum(group['daily_kg'] for group in groups)
        in_store = sum(
            batch['remaining_kg']
            for batch in FeedingInstructionService.active_batches(tenant_id)
            if batch['recipe_type'] == normalized_type
        )
        needed = max(daily_demand * days - in_store, 0.0)
        suggested = math.ceil(needed / ROUND_TO_KG) * ROUND_TO_KG if needed > 0 else 0

        if not groups:
            reason = 'No feeding group has this mix assigned with a usable daily amount yet.'
        elif suggested == 0:
            reason = f'The mix already in store covers {days} days.'
        else:
            reason = None
        return {
            'recipe_type': normalized_type,
            'days': days,
            'daily_demand_kg': round(daily_demand, 2),
            'in_store_kg': round(in_store, 2),
            'suggested_batch_kg': suggested,
            'recipe_id': recipe['id'] if recipe else None,
            'max_batch_kg': capacity['max_batch_kg'],
            'limiting_ingredient': capacity['limiting_ingredient'],
            'groups': groups,
            'reason': reason,
        }

    @staticmethod
    def _recipe_to_mix(plan_groups: list[dict], recipe_type: str) -> dict | None:
        """The assigned mix of this type that feeds the most; groups normally share one."""
        demand_by_recipe = defaultdict(float)
        recipes = {}
        for row in plan_groups:
            recipe = row.get('assigned_recipe') or {}
            if recipe.get('recipe_type') != recipe_type:
                continue
            recipes[recipe['id']] = recipe
            demand_by_recipe[recipe['id']] += row.get('daily_group_batch_kg') or 0
        if not recipes:
            return None
        return recipes[max(demand_by_recipe, key=lambda recipe_id: (demand_by_recipe[recipe_id], recipe_id))]

    @staticmethod
    def _stock_capacity(tenant_id: int, recipe: dict | None) -> dict:
        """Largest batch of the mix that current stock allows at its saved shares, rounded down to 0.1 kg."""
        shares = {
            ingredient['inventory_item_id']: ingredient['percentage']
            for ingredient in (recipe or {}).get('ingredients', [])
            if ingredient.get('inventory_item_id') and ingredient.get('percentage', 0) > 0
        }
        if not shares:
            return {'max_batch_kg': None, 'limiting_ingredient': None}
        stock = {item.id: item for item in InventoryRepository.get_items_by_ids(tenant_id, list(shares))}
        limits = [
            (float(stock[item_id].current_qty or 0) * 100 / share if item_id in stock else 0.0, item_id)
            for item_id, share in shares.items()
        ]
        max_kg, limiting_id = min(limits)
        limiting = stock.get(limiting_id)
        return {
            'max_batch_kg': math.floor(max_kg * 10) / 10,
            'limiting_ingredient': {
                'inventory_item_id': limiting_id,
                'name': limiting.name if limiting else None,
                'in_stock_kg': float(limiting.current_qty or 0) if limiting else 0.0,
            },
        }

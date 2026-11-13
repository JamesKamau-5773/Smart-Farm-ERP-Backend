"""Today's feeding instructions for the people doing the feeding.

Built from the group feeding plan and active batch stock, but deliberately
without prices, costs or recipe ingredient shares: staff granted only the
'feeding' page see what to feed, not how the mix was formulated or priced.
"""
from __future__ import annotations

from app.models.supply import FeedBatch, FeedRecipe
from app.services.group_feeding_plan_service import GroupFeedingPlanService
from app.services.nutrition_service import NutritionService
from app.utils.farm_time import farm_today

_GROUP_FIELDS = (
    'feeding_group', 'headcount', 'quantity_basis', 'quantity_label', 'feeding_times_per_day',
    'daily_kg_per_head', 'kg_per_head_per_feeding', 'daily_group_batch_kg',
    'group_batch_per_feeding_kg', 'physical_measures', 'requires_concentrate_rate',
)

# Checked in this order; a group reports the first reason that applies.
NOT_READY_MESSAGES = {
    'NO_MIX': 'No mix is assigned to this group yet.',
    'NO_ANIMALS': 'There are no animals in this group.',
    'NO_CONCENTRATE_RATE': 'Set the kg per head per day on this mix before feeding it.',
    'NO_ACTIVE_BATCH': 'No batch of this mix is in store. Mix a batch first.',
}


class FeedingInstructionService:
    @staticmethod
    def today(tenant_id: int) -> dict:
        plan = GroupFeedingPlanService.calculate_plan_by_group(tenant_id)
        active_batches = FeedingInstructionService.active_batches(tenant_id)
        batch_by_type = {batch['recipe_type']: batch for batch in active_batches}

        groups = []
        for row in plan['groups']:
            recipe = row.get('assigned_recipe')
            instruction = {field: row.get(field) for field in _GROUP_FIELDS}
            instruction['mix_name'] = recipe['name'] if recipe else None
            instruction['recipe_type'] = recipe['recipe_type'] if recipe else None
            instruction['active_batch_id'] = (batch_by_type.get(recipe['recipe_type']) or {}).get('batch_id') if recipe else None
            reason = FeedingInstructionService._not_ready_reason(row, instruction['active_batch_id'])
            instruction['ready'] = reason is None
            instruction['not_ready_reason'] = reason
            instruction['not_ready_message'] = NOT_READY_MESSAGES.get(reason)
            groups.append(instruction)

        return {
            'date': farm_today().isoformat(),
            'groups': groups,
            'active_batches': active_batches,
            'totals': {
                'total_active_animals': plan['totals']['total_active_animals'],
                'total_daily_feed_kg': plan['totals']['total_daily_feed_kg'],
            },
        }

    @staticmethod
    def _not_ready_reason(row: dict, active_batch_id) -> str | None:
        if not row.get('assigned_recipe'):
            return 'NO_MIX'
        if not row.get('headcount'):
            return 'NO_ANIMALS'
        if row.get('requires_concentrate_rate'):
            return 'NO_CONCENTRATE_RATE'
        if active_batch_id is None:
            return 'NO_ACTIVE_BATCH'
        return None

    @staticmethod
    def active_batches(tenant_id: int) -> list[dict]:
        batches = (
            FeedBatch.query.filter_by(tenant_id=tenant_id, status='ACTIVE')
            .order_by(FeedBatch.mixed_on.desc(), FeedBatch.id.desc())
            .all()
        )
        recipe_ids = {batch.recipe_id for batch in batches if batch.recipe_id}
        recipe_types = dict(
            FeedRecipe.query.with_entities(FeedRecipe.id, FeedRecipe.recipe_type)
            .filter(FeedRecipe.tenant_id == tenant_id, FeedRecipe.id.in_(recipe_ids))
            .all()
        ) if recipe_ids else {}
        result = []
        for batch in batches:
            pace = NutritionService.batch_consumption_pace(batch, tenant_id=tenant_id)
            result.append({
                'batch_id': batch.id,
                'batch_name': batch.batch_name,
                'recipe_type': recipe_types.get(batch.recipe_id),
                'mixed_on': str(batch.mixed_on),
                'total_weight_kg': float(batch.total_weight),
                'remaining_kg': pace['remaining_kg'],
                'daily_feeding_rate_kg': pace['daily_feeding_rate_kg'],
                'days_until_empty': pace['days_until_empty'],
            })
        return result

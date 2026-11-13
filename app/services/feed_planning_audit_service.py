"""What gets written to the audit log for feed-planning events."""
from __future__ import annotations

from sqlalchemy import inspect

from app.services.audit_service import record_request_audit


def _pending_changes(model) -> tuple[dict, dict]:
    """(old, new) values of the model's modified column attributes, before flush."""
    old, new = {}, {}
    state = inspect(model)
    for attr in state.mapper.column_attrs:
        history = state.attrs[attr.key].history
        if history.has_changes():
            old[attr.key] = history.deleted[0] if history.deleted else None
            new[attr.key] = history.added[0] if history.added else None
    return old, new


class FeedPlanningAuditService:
    @staticmethod
    def recipe_saved(recipe_id: int, details: dict) -> None:
        record_request_audit('FEED_RECIPE_SAVE', 'FeedRecipe', recipe_id, new_value=details)

    @staticmethod
    def stage_recipe_update(recipe) -> None:
        """Call before committing the edit so the audit entry is saved with it."""
        old, new = _pending_changes(recipe)
        if new:
            record_request_audit('FEED_RECIPE_UPDATE', 'FeedRecipe', recipe.id, old_value=old, new_value=new, commit=False)

    @staticmethod
    def stage_recipe_delete(recipe) -> None:
        record_request_audit(
            'FEED_RECIPE_DELETE', 'FeedRecipe', recipe.id,
            old_value={'name': recipe.recipe_name, 'recipe_type': recipe.recipe_type, 'feeding_group': recipe.feeding_group},
            commit=False,
        )

    @staticmethod
    def feeding_profile_saved(profile_id: int, feeding_group: str, values: dict) -> None:
        record_request_audit(
            'FEEDING_GROUP_PROFILE_SAVE', 'FeedingGroupProfile', profile_id,
            new_value={'feeding_group': feeding_group, **values},
        )

    @staticmethod
    def batch_mixed(batch: dict) -> None:
        batch_id = batch.get('batchId') or batch.get('batch_id') or batch.get('id')
        if batch_id:
            record_request_audit('FEED_BATCH_MIX', 'FeedBatch', int(batch_id), new_value={
                key: batch.get(key) for key in ('batchName', 'totalWeight', 'totalCost', 'costPerKg', 'mixedOn')
                if key in batch
            })

    @staticmethod
    def feeding_recorded(batch_id: int, event: dict) -> None:
        record_request_audit('FEED_CONSUMPTION_RECORD', 'FeedBatch', batch_id, new_value={
            key: event.get(key) for key in ('eventId', 'consumedWeight', 'consumedOn', 'feedingGroup', 'remainingWeight')
            if key in event
        })

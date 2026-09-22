from __future__ import annotations

from app.services.feed_mixer_policy_service import FeedMixerPolicyService
from app.services.group_feeding_plan_service import GroupFeedingPlanService


class FeedingGroupRecipePolicyService:
    """Policy rules that map biological feeding groups to recipe mixer types."""

    _GROUP_ALLOWED_MIXERS = {
        'lactating': {
            FeedMixerPolicyService.DAIRY_MEAL,
            FeedMixerPolicyService.MAIN_MEAL,
        },
        'dry': {FeedMixerPolicyService.MAIN_MEAL},
        'calf_0_3m': {FeedMixerPolicyService.DAIRY_MEAL},
        'calf_3_6m': {FeedMixerPolicyService.MAIN_MEAL},
        'heifer': {FeedMixerPolicyService.MAIN_MEAL},
    }

    @classmethod
    def normalize_feeding_group(cls, feeding_group: str | None) -> str | None:
        if feeding_group is None:
            return None
        return GroupFeedingPlanService.normalize_group_name(feeding_group)

    @classmethod
    def default_recipe_type_for_group(cls, feeding_group: str | None) -> str:
        group = cls.normalize_feeding_group(feeding_group)
        if group == 'calf_0_3m':
            return FeedMixerPolicyService.DAIRY_MEAL
        return FeedMixerPolicyService.MAIN_MEAL

    @classmethod
    def allowed_recipe_types_for_group(cls, feeding_group: str | None) -> set[str]:
        group = cls.normalize_feeding_group(feeding_group)
        if group is None:
            return {
                FeedMixerPolicyService.DAIRY_MEAL,
                FeedMixerPolicyService.MAIN_MEAL,
            }
        return set(cls._GROUP_ALLOWED_MIXERS[group])

    @classmethod
    def resolve_recipe_type(cls, *, feeding_group: str | None, requested_recipe_type: str | None) -> str:
        normalized_group = cls.normalize_feeding_group(feeding_group)
        normalized_recipe_type = FeedMixerPolicyService.normalize_recipe_type(
            requested_recipe_type,
            default=None,
        )

        if normalized_group is None:
            return normalized_recipe_type or FeedMixerPolicyService.MAIN_MEAL

        allowed = cls.allowed_recipe_types_for_group(normalized_group)
        recipe_type = normalized_recipe_type or cls.default_recipe_type_for_group(normalized_group)
        if recipe_type not in allowed:
            allowed_str = ', '.join(sorted(allowed))
            raise ValueError(
                f"feeding_group '{normalized_group}' only supports recipe_type(s): {allowed_str}."
            )
        return recipe_type

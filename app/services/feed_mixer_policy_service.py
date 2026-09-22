from __future__ import annotations

from decimal import Decimal

from app.models.supply import InventoryItem


class FeedMixerPolicyService:
    """Backend source-of-truth for feed mixer eligibility and defaults."""

    DAIRY_MEAL = 'dairy_meal'
    MAIN_MEAL = 'main_meal'

    VALID_MIXERS = {DAIRY_MEAL, MAIN_MEAL}
    VALID_ROLES = {
        'concentrate_component',
        'roughage',
        'premix',
        'dairy_meal_product',
    }

    _DAIRY_MEAL_PRODUCT_KEYWORDS = (
        'dairy meal',
    )
    _PREMIX_KEYWORDS = (
        'premix',
        'mineral mix',
        'vitamin mix',
        'additive',
        'premi',
    )
    _CONCENTRATE_KEYWORDS = (
        'maize germ',
        'maize bran',
        'wheat bran',
        'pollard',
        'cotton seed cake',
        'sunflower cake',
        'sunflower meal',
        'soya',
        'soybean meal',
        'canola meal',
        'molasses',
        'concentrate',
        'cake',
        'bran',
        'germ',
    )
    _ROUGHAGE_KEYWORDS = (
        'hay',
        'silage',
        'napier',
        'grass',
        'stalk',
        'stover',
        'fodder',
        'roughage',
        'chaff',
        'pasture',
    )

    @staticmethod
    def _to_decimal(value) -> Decimal:
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal('0')

    @staticmethod
    def _normalize(value: str | None) -> str:
        return ' '.join((value or '').strip().lower().split())

    @classmethod
    def normalize_recipe_type(cls, value: str | None, *, default: str | None = None) -> str | None:
        normalized = cls._normalize(value)
        if normalized in cls.VALID_MIXERS:
            return normalized
        if normalized in {'dairy', 'dairymeal', 'dairy-meal'}:
            return cls.DAIRY_MEAL
        if normalized in {'main', 'mainmeal', 'main-meal'}:
            return cls.MAIN_MEAL
        return default

    @classmethod
    def normalize_allowed_mixers(cls, value, *, fallback: list[str] | None = None) -> list[str]:
        if isinstance(value, str):
            tokens = [token.strip() for token in value.split(',') if token.strip()]
        elif isinstance(value, (list, tuple, set)):
            tokens = [str(token).strip() for token in value if str(token).strip()]
        elif value is None:
            tokens = []
        else:
            tokens = [str(value).strip()]

        normalized = []
        for token in tokens:
            mixer = cls.normalize_recipe_type(token)
            if mixer and mixer not in normalized:
                normalized.append(mixer)

        if normalized:
            return normalized

        return list(fallback or [cls.MAIN_MEAL])

    @classmethod
    def normalize_role(cls, role: str | None, *, allowed_mixers: list[str], fallback_name: str | None = None, fallback_category: str | None = None) -> str:
        normalized = cls._normalize(role)
        if normalized in cls.VALID_ROLES:
            return normalized

        inferred = cls.infer_policy_from_item(name=fallback_name, category=fallback_category)
        if inferred['role']:
            return inferred['role']

        if cls.DAIRY_MEAL in allowed_mixers and cls.MAIN_MEAL in allowed_mixers:
            return 'dairy_meal_product'
        if cls.DAIRY_MEAL in allowed_mixers:
            return 'concentrate_component'
        return 'roughage'

    @classmethod
    def infer_policy_from_item(cls, *, name: str | None, category: str | None) -> dict:
        normalized_name = cls._normalize(name)
        normalized_category = cls._normalize(category)

        # Explicit dairy meal product can be intentionally available to both mixers.
        if any(keyword in normalized_name for keyword in cls._DAIRY_MEAL_PRODUCT_KEYWORDS):
            return {
                'allowed_mixers': [cls.DAIRY_MEAL, cls.MAIN_MEAL],
                'role': 'dairy_meal_product',
            }

        if any(keyword in normalized_name for keyword in cls._PREMIX_KEYWORDS):
            # Premixes/additives are blended into the dairy meal only; the main
            # meal receives them via the formulated dairy meal product.
            return {
                'allowed_mixers': [cls.DAIRY_MEAL],
                'role': 'premix',
            }

        if any(keyword in normalized_name for keyword in cls._CONCENTRATE_KEYWORDS):
            # Raw concentrate components belong in the dairy meal. The main
            # meal (TMR) includes the formulated dairy meal product rather
            # than the individual concentrate components.
            return {
                'allowed_mixers': [cls.DAIRY_MEAL],
                'role': 'concentrate_component',
            }

        if any(keyword in normalized_name for keyword in cls._ROUGHAGE_KEYWORDS):
            return {
                'allowed_mixers': [cls.MAIN_MEAL],
                'role': 'roughage',
            }

        if normalized_category in {'bulk feed', 'forage', 'roughage', 'fodder'}:
            return {
                'allowed_mixers': [cls.MAIN_MEAL],
                'role': 'roughage',
            }

        if normalized_category in {'supplement', 'premix'}:
            return {
                'allowed_mixers': [cls.DAIRY_MEAL],
                'role': 'premix',
            }

        if normalized_category in {'feed'}:
            # Generic feed is treated as main meal unless explicitly marked as concentrate by name.
            return {
                'allowed_mixers': [cls.MAIN_MEAL],
                'role': 'roughage',
            }

        return {
            'allowed_mixers': [cls.MAIN_MEAL],
            'role': 'roughage',
        }

    @classmethod
    def resolve_item_policy(cls, item: InventoryItem) -> dict:
        inferred = cls.infer_policy_from_item(name=item.name, category=item.category)

        allowed_mixers = cls.normalize_allowed_mixers(
            getattr(item, 'allowed_mixers', None),
            fallback=inferred['allowed_mixers'],
        )
        role = cls.normalize_role(
            getattr(item, 'mixer_role', None),
            allowed_mixers=allowed_mixers,
            fallback_name=item.name,
            fallback_category=item.category,
        )

        defaults = {
            cls.DAIRY_MEAL: float(cls._to_decimal(getattr(item, 'inclusion_percentage_dairy_meal', 0))),
            cls.MAIN_MEAL: float(cls._to_decimal(getattr(item, 'inclusion_percentage_main_meal', 0))),
        }

        return {
            'allowed_mixers': allowed_mixers,
            'role': role,
            'defaults': defaults,
        }

    @classmethod
    def apply_recipe_overrides(cls, *, policy: dict, item_id: int, mix_share_defaults_by_mixer: dict | None) -> dict:
        defaults = dict(policy.get('defaults') or {})
        if not mix_share_defaults_by_mixer:
            return defaults

        for mixer in cls.VALID_MIXERS:
            mixer_defaults = mix_share_defaults_by_mixer.get(mixer) or {}
            if item_id in mixer_defaults:
                defaults[mixer] = float(mixer_defaults[item_id])
        return defaults

    @classmethod
    def is_allowed_for_mixer(cls, policy: dict, recipe_type: str) -> bool:
        normalized = cls.normalize_recipe_type(recipe_type)
        if normalized is None:
            return False
        return normalized in (policy.get('allowed_mixers') or [])

    @classmethod
    def validate_items_for_recipe_type(
        cls,
        *,
        tenant_id: int,
        ingredient_ids: list[int],
        recipe_type: str,
    ) -> tuple[list[InventoryItem], list[int], list[int]]:
        """Return rows plus missing and ineligible ids for recipe_type validation."""
        normalized_recipe_type = cls.normalize_recipe_type(recipe_type)
        if normalized_recipe_type is None:
            raise ValueError('recipe_type must be one of: dairy_meal, main_meal.')

        unique_ids = []
        for ingredient_id in ingredient_ids:
            if ingredient_id not in unique_ids:
                unique_ids.append(ingredient_id)

        if not unique_ids:
            return [], [], []

        rows = (
            InventoryItem.query
            .filter(InventoryItem.tenant_id == tenant_id, InventoryItem.id.in_(unique_ids))
            .all()
        )
        by_id = {row.id: row for row in rows}

        missing_ids = [ingredient_id for ingredient_id in unique_ids if ingredient_id not in by_id]

        ineligible_ids = []
        for ingredient_id in unique_ids:
            row = by_id.get(ingredient_id)
            if not row:
                continue
            policy = cls.resolve_item_policy(row)
            if normalized_recipe_type not in policy['allowed_mixers']:
                ineligible_ids.append(ingredient_id)

        return rows, missing_ids, ineligible_ids

    @classmethod
    def infer_unique_recipe_type(cls, *, tenant_id: int, ingredient_ids: list[int]) -> str | None:
        """Infer a mixer only when every selected item permits one common mixer."""
        unique_ids = list(dict.fromkeys(ingredient_ids))
        if not unique_ids:
            return None

        rows = (
            InventoryItem.query
            .filter(InventoryItem.tenant_id == tenant_id, InventoryItem.id.in_(unique_ids))
            .all()
        )
        if len(rows) != len(unique_ids):
            return None

        common_mixers = set(cls.VALID_MIXERS)
        for row in rows:
            common_mixers.intersection_update(cls.resolve_item_policy(row)['allowed_mixers'])

        return next(iter(common_mixers)) if len(common_mixers) == 1 else None

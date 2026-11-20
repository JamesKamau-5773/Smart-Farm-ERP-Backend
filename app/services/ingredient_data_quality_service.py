"""Plausibility checks for ingredient nutrient values.

Crude protein is stored in g/kg. A common entry mistake is typing the
percentage (e.g. 30 for sunflower cake) into the g/kg field, which makes every
mix that uses the ingredient look ten times lower in protein than it is.
Feeds that contain protein essentially never fall below ~40 g/kg, while
minerals, premixes and salts are 0, so a value strictly between 0 and the
threshold is almost certainly a percentage.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, List

from app.repositories.supply_repo import InventoryRepository

PROTEIN_LIKELY_PERCENT = 'PROTEIN_LIKELY_PERCENT'

_MIN_PLAUSIBLE_PROTEIN_G_PER_KG = Decimal('40')
_MAX_PROTEIN_G_PER_KG = Decimal('999.99')
_MAX_ENERGY_MJ_PER_KG = Decimal('30')
_MAX_FIBER_G_PER_KG = Decimal('999.99')


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception:
        return Decimal('0')


def _number(value: Decimal) -> str:
    """18.00 -> '18', 1.80 -> '1.8', 300 -> '300'."""
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


class IngredientDataQualityService:
    @staticmethod
    def warnings_for(item) -> List[dict]:
        protein = _decimal(getattr(item, 'protein_grams_per_kg', 0))
        warnings = []
        if Decimal('0') < protein < _MIN_PLAUSIBLE_PROTEIN_G_PER_KG:
            suggested = protein * 10
            warnings.append({
                'code': PROTEIN_LIKELY_PERCENT,
                'field': 'protein_grams_per_kg',
                'value': float(protein),
                'suggested_value': float(suggested),
                'message': (
                    f'{item.name} has {_number(protein)} g/kg crude protein ({_number(protein / 10)}%), '
                    f'which is unusually low. If {_number(protein)}% was meant, the value should be '
                    f'{_number(suggested)} g/kg.'
                ),
            })
        return warnings

    @staticmethod
    def correction_for(item, code: str) -> dict:
        """Field values that resolve the given warning, recomputed from the item's current data."""
        for warning in IngredientDataQualityService.warnings_for(item):
            if warning['code'] == code:
                return {warning['field']: Decimal(str(warning['suggested_value']))}
        raise ValueError('This item has no such data warning to fix.')

    @staticmethod
    def suspect_ingredients_for_ids(tenant_id: int, ingredient_ids: Iterable[int]) -> List[dict]:
        items = InventoryRepository.get_items_by_ids(tenant_id, list(ingredient_ids))
        return IngredientDataQualityService.suspect_ingredients(items)

    @staticmethod
    def suspect_ingredients(items: Iterable) -> List[dict]:
        suspects = []
        for item in items:
            warnings = IngredientDataQualityService.warnings_for(item)
            if warnings:
                suspects.append({'ingredient_id': item.id, 'name': item.name, 'warnings': warnings})
        return suspects

    @staticmethod
    def validate_nutrient_ranges(data: dict) -> None:
        """Rejects values that are impossible rather than merely suspicious."""
        limits = {
            'protein_grams_per_kg': ('Crude protein', _MAX_PROTEIN_G_PER_KG, 'g/kg'),
            'energy_mj_per_kg': ('Energy', _MAX_ENERGY_MJ_PER_KG, 'MJ/kg'),
            'fiber_grams_per_kg': ('Fiber', _MAX_FIBER_G_PER_KG, 'g/kg'),
        }
        for field, (label, maximum, unit) in limits.items():
            if data.get(field) in (None, ''):
                continue
            value = _decimal(data[field])
            if value < 0 or value > maximum:
                raise ValueError(f'{label} must be between 0 and {maximum:g} {unit}.')

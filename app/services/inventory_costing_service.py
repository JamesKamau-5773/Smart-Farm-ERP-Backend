"""Inventory valuation rules."""
from __future__ import annotations

from decimal import Decimal

_CENTS = Decimal('0.01')


class InventoryCostingService:
    @staticmethod
    def weighted_average_cost(
        *,
        on_hand_qty: Decimal,
        current_unit_cost: Decimal,
        received_qty: Decimal,
        received_unit_cost: Decimal,
    ) -> Decimal:
        """Moving weighted-average unit cost after a priced delivery."""
        on_hand = max(Decimal(str(on_hand_qty or 0)), Decimal('0'))
        if on_hand == 0:
            return received_unit_cost.quantize(_CENTS)
        total_value = on_hand * Decimal(str(current_unit_cost or 0)) + received_qty * received_unit_cost
        return (total_value / (on_hand + received_qty)).quantize(_CENTS)

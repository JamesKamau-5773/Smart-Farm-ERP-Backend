from __future__ import annotations
"""
Service for recipe formulation with protein targeting.
Single Responsibility: Calculate and adjust ingredient percentages to hit target protein levels.
"""
from decimal import Decimal, InvalidOperation
from typing import Optional

from app import db
from app.models.supply import InventoryItem, FeedRecipe, RecipeIngredient
from app.services.feed_mixer_policy_service import FeedMixerPolicyService
from app.services.feeding_group_recipe_policy_service import FeedingGroupRecipePolicyService
from app.repositories.cow_repo import CowRepository


class FormulationInfeasibleError(ValueError):
    """Raised when the selected ingredients cannot meet a nutrient target."""

    def __init__(
        self,
        message: str,
        *,
        target_protein_percent: float | None = None,
        minimum_achievable_protein_percent: float | None = None,
        maximum_achievable_protein_percent: float | None = None,
    ):
        super().__init__(message)
        self.target_protein_percent = target_protein_percent
        self.minimum_achievable_protein_percent = minimum_achievable_protein_percent
        self.maximum_achievable_protein_percent = maximum_achievable_protein_percent
        self.limiting_ingredients: list[dict] = []
        self.max_feasible_mix: list[dict] = []


class RecipeFormulationService:
    """Handles recipe creation with automatic protein targeting and ingredient adjustment."""

    @staticmethod
    def _validate_recipe_ingredients(tenant_id: int, ingredients: list[dict]) -> dict[int, InventoryItem]:
        if not ingredients:
            raise ValueError("At least one ingredient is required.")

        ingredient_ids = []
        total_percentage = Decimal("0")
        for ingredient in ingredients:
            try:
                ingredient_id = int(ingredient["ingredient_id"])
                percentage_raw = ingredient.get("percentage", ingredient.get("adjusted_percentage"))
                percentage = Decimal(str(percentage_raw))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                raise ValueError("Each ingredient requires a valid ingredient_id and percentage.")
            if percentage <= 0 or percentage > 100:
                raise ValueError("Each ingredient percentage must be greater than 0 and no more than 100.")
            ingredient_ids.append(ingredient_id)
            total_percentage += percentage
            ingredient["percentage"] = float(percentage)

        if len(set(ingredient_ids)) != len(ingredient_ids):
            raise ValueError("Each ingredient may appear only once in a recipe.")
        if abs(total_percentage - Decimal("100")) > Decimal("0.01"):
            raise ValueError(f"Ingredient percentages must total 100; got {total_percentage}.")

        inventory_items = InventoryItem.query.filter(
            InventoryItem.tenant_id == tenant_id,
            InventoryItem.id.in_(ingredient_ids),
        ).all()
        item_lookup = {item.id: item for item in inventory_items}
        missing_ids = [ingredient_id for ingredient_id in ingredient_ids if ingredient_id not in item_lookup]
        if missing_ids:
            raise ValueError(f"Ingredient(s) not found for tenant: {missing_ids}.")

        invalid_protein = [
            item.name for item in inventory_items
            if Decimal(str(item.protein_grams_per_kg or 0)) < 0
        ]
        if invalid_protein:
            raise ValueError(
                "protein_grams_per_kg cannot be negative for: " + ", ".join(sorted(invalid_protein)) + "."
            )
        return item_lookup

    @staticmethod
    def _seed_percentages_when_all_zero(base_ingredients: list[dict], ingredient_lookup: dict[int, dict]) -> list[dict]:
        """Seed percentages when UI submits all-zero shares so auto-adjust can converge.

        Uses equal split so the first auto-adjust action produces visible movement.
        """
        if not base_ingredients:
            return []

        equal_pct = 100.0 / len(base_ingredients)
        seeded = [{"ingredient_id": ing["ingredient_id"], "percentage": equal_pct} for ing in base_ingredients]

        # Ensure sum is exactly 100 after rounding.
        rounded = []
        running = 0.0
        for idx, ing in enumerate(seeded):
            if idx == len(seeded) - 1:
                pct = round(100.0 - running, 2)
            else:
                pct = round(float(ing["percentage"]), 2)
                running += pct
            rounded.append({"ingredient_id": ing["ingredient_id"], "percentage": max(0.0, pct)})
        return rounded

    @staticmethod
    def get_ingredient_nutrition_profile(ingredient_id: int, tenant_id: int) -> dict:
        """
        Get nutritional profile of an ingredient.

        Returns:
        {
            "ingredient_id": int,
            "name": str,
            "protein_grams_per_kg": float,
            "energy_mj_per_kg": float,
            "fiber_grams_per_kg": float,
            "cost_per_kg": float,
        }
        """
        ingredient = InventoryItem.query.filter_by(id=ingredient_id, tenant_id=tenant_id).first()
        if not ingredient:
            raise ValueError(f"Ingredient {ingredient_id} not found for this tenant.")

        return {
            "ingredient_id": ingredient.id,
            "name": ingredient.name,
            "protein_grams_per_kg": float(ingredient.protein_grams_per_kg),
            "energy_mj_per_kg": float(ingredient.energy_mj_per_kg),
            "fiber_grams_per_kg": float(ingredient.fiber_grams_per_kg),
            "cost_per_kg": float(ingredient.cost_per_kg),
        }

    @staticmethod
    def calculate_batch_protein_content(
        batch_size_kg: float,
        ingredients_with_percentages: list[dict],  # [{"ingredient_id": int, "percentage": float}, ...]
        tenant_id: int | None = None,
    ) -> dict:
        """
        Calculate total and average protein in a batch given ingredient percentages.

        Returns:
        {
            "batch_size_kg": float,
            "ingredients": [
                {
                    "ingredient_id": int,
                    "percentage": float,
                    "weight_kg": float,
                    "protein_grams_per_kg": float,
                    "total_protein_grams": float,
                }
            ],
            "total_protein_grams": float,
            "average_protein_percent": float,  # (total_protein_grams / batch_size_kg) / 10
        }
        """
        total_protein_grams = 0
        ingredient_details = []

        for ing_data in ingredients_with_percentages:
            ingredient_id = ing_data["ingredient_id"]
            percentage = float(ing_data["percentage"])

            # Weight of this ingredient in batch
            weight_kg = (percentage / 100.0) * batch_size_kg

            # Fetch ingredient nutrition
            ingredient_query = InventoryItem.query.filter_by(id=ingredient_id)
            if tenant_id is not None:
                ingredient_query = ingredient_query.filter_by(tenant_id=tenant_id)
            ingredient = ingredient_query.first()
            if not ingredient:
                raise ValueError(f"Ingredient {ingredient_id} not found for this tenant.")

            protein_per_kg = float(ingredient.protein_grams_per_kg)
            total_protein = weight_kg * protein_per_kg

            total_protein_grams += total_protein

            ingredient_details.append({
                "ingredient_id": ingredient_id,
                "percentage": percentage,
                "weight_kg": round(weight_kg, 2),
                "protein_grams_per_kg": protein_per_kg,
                "total_protein_grams": round(total_protein, 2),
            })

        # Average protein as percentage: (grams / kg_of_batch) / 10 = percent
        average_protein_percent = (total_protein_grams / (batch_size_kg * 1000)) * 100 if batch_size_kg > 0 else 0

        return {
            "batch_size_kg": batch_size_kg,
            "ingredients": ingredient_details,
            "total_protein_grams": round(total_protein_grams, 2),
            "average_protein_percent": round(average_protein_percent, 4),
        }

    @staticmethod
    def suggest_ingredient_adjustments(
        tenant_id: int,
        batch_size_kg: float,
        base_ingredients: list[dict],  # [{"ingredient_id": int, "percentage": float}, ...]
        target_protein_percent: float,
        recipe_type: str | None = None,
        feeding_group: str | None = None,
    ) -> dict:
        """
        Suggest adjustments to ingredient percentages to achieve target protein.
        Uses a simple proportional scaling algorithm.

        Returns:
        {
            "current_protein_percent": float,
            "target_protein_percent": float,
            "adjustment_needed": float,  # percentage points
            "adjusted_ingredients": [
                {
                    "ingredient_id": int,
                    "name": str,
                    "current_percentage": float,
                    "adjusted_percentage": float,
                    "adjustment": float,
                    "protein_grams_per_kg": float,
                }
            ],
            "projected_nutrition": {
                "total_protein_grams": float,
                "average_protein_percent": float,
            },
            "adjustment_strategy": str,
        }
        """
        normalized_feeding_group = FeedingGroupRecipePolicyService.normalize_feeding_group(feeding_group)
        normalized_recipe_type = FeedingGroupRecipePolicyService.resolve_recipe_type(
            feeding_group=normalized_feeding_group,
            requested_recipe_type=recipe_type,
        )
        ingredient_ids = [int(ing["ingredient_id"]) for ing in base_ingredients]
        _, missing_ids, ineligible_ids = FeedMixerPolicyService.validate_items_for_recipe_type(
            tenant_id=tenant_id,
            ingredient_ids=ingredient_ids,
            recipe_type=normalized_recipe_type,
        )
        if missing_ids:
            raise ValueError(f"Ingredient(s) not found for tenant: {missing_ids}.")
        if ineligible_ids:
            raise ValueError(
                f"Ingredient(s) not eligible for recipe_type {normalized_recipe_type}: {ineligible_ids}."
            )

        # Pre-load ingredient metadata used by both seeding and adjustments.
        ingredient_lookup = {}
        for ing in base_ingredients:
            ing_obj = InventoryItem.query.filter_by(id=ing["ingredient_id"], tenant_id=tenant_id).first()
            protein = float(ing_obj.protein_grams_per_kg) if ing_obj else 0
            cost_per_kg = float(ing_obj.cost_per_kg) if ing_obj and ing_obj.cost_per_kg is not None else 0.0
            available_qty_kg = float(ing_obj.current_qty) if ing_obj and ing_obj.current_qty is not None else 0.0
            ingredient_lookup[ing["ingredient_id"]] = {
                "protein_per_kg": protein,
                "name": ing_obj.name if ing_obj else f"Ingredient {ing['ingredient_id']}",
                "current_pct": ing["percentage"],
                "cost_per_kg": max(0.0, cost_per_kg),
                "available_qty_kg": max(0.0, available_qty_kg),
            }

        # If all shares are zero, seed a valid baseline so auto-adjust can produce non-zero output.
        if base_ingredients and all(float(ing.get("percentage") or 0) <= 0 for ing in base_ingredients):
            base_ingredients = RecipeFormulationService._seed_percentages_when_all_zero(base_ingredients, ingredient_lookup)
            for ing in base_ingredients:
                ingredient_lookup[ing["ingredient_id"]]["current_pct"] = ing["percentage"]

        # Get current nutrition profile
        current = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg,
            base_ingredients,
            tenant_id=tenant_id,
        )
        current_protein = current["average_protein_percent"]

        # Calculate adjustment needed
        adjustment_needed = target_protein_percent - current_protein

        zero_share_present = any(float(ing.get("percentage") or 0) <= 1e-9 for ing in base_ingredients)
        if abs(adjustment_needed) < 1e-6 and (len(base_ingredients) <= 1 or not zero_share_present):
            return {
                "current_protein_percent": current_protein,
                "target_protein_percent": target_protein_percent,
                "adjustment_needed": 0,
                "adjusted_ingredients": [
                    {
                        "ingredient_id": ing["ingredient_id"],
                        "current_percentage": ing["percentage"],
                        "adjusted_percentage": ing["percentage"],
                        "adjustment": 0,
                    }
                    for ing in base_ingredients
                ],
                "projected_nutrition": current,
                "adjustment_strategy": "No adjustment needed - target already achieved.",
            }
        # When the target is met only because some ingredients sit at 0%, fall
        # through so the full-participation solver can bring every feed into
        # the mix while keeping the protein target.

        proteins = [ingredient_lookup[ing["ingredient_id"]]["protein_per_kg"] for ing in base_ingredients]
        # g/kg divided by 10 is protein expressed as a percentage of the mix.
        minimum_achievable = min(proteins) / 10.0
        maximum_achievable = max(proteins) / 10.0
        target = float(target_protein_percent)
        adjusted_percentages = {
            ing["ingredient_id"]: float(ing["percentage"])
            for ing in base_ingredients
        }
        protein_percent = {
            ing_id: metadata["protein_per_kg"] / 10.0
            for ing_id, metadata in ingredient_lookup.items()
        }
        # An ingredient can never take a larger share of the batch than its
        # in-stock quantity allows for this batch size. This is the same
        # consumption math the batch processor applies (share% * batch_kg).
        stock_cap_pct = {}
        for ing_id, metadata in ingredient_lookup.items():
            if float(batch_size_kg) > 1e-9:
                stock_cap_pct[ing_id] = metadata["available_qty_kg"] * 100.0 / float(batch_size_kg)
            else:
                stock_cap_pct[ing_id] = 100.0

        def _build_unreachable_target_message() -> str:
            return (
                f"Cannot reach {target:g}% protein with the selected in-stock ingredients. "
                f"Maximum achievable target protein with these feeds is {maximum_achievable:g}% "
                f"(minimum is {minimum_achievable:g}%)."
            )

        def _raise_unreachable_target() -> None:
            raise FormulationInfeasibleError(
                _build_unreachable_target_message(),
                target_protein_percent=target,
                minimum_achievable_protein_percent=minimum_achievable,
                maximum_achievable_protein_percent=maximum_achievable,
            )

        def _build_fallback_feasible_mix() -> dict[int, float] | None:
            """Build a guaranteed-feasible mix when target lies within [min, max].

            Uses tiny floor shares for all ingredients where possible, then solves
            the remaining mass between min/max-protein anchors.
            """
            ingredient_ids = list(protein_percent.keys())
            if len(ingredient_ids) < 2:
                return None

            low_id = min(ingredient_ids, key=lambda i: protein_percent[i])
            high_id = max(ingredient_ids, key=lambda i: protein_percent[i])
            low_protein = protein_percent[low_id]
            high_protein = protein_percent[high_id]
            spread = high_protein - low_protein
            if spread <= 1e-9:
                return None

            for floor_pct in (1.0, 0.5, 0.1, 0.0):
                if floor_pct * len(ingredient_ids) > 100.0 + 1e-9:
                    continue

                remaining_pct = 100.0 - floor_pct * len(ingredient_ids)
                base_protein_mass = floor_pct * sum(protein_percent[i] for i in ingredient_ids)
                required_protein_mass = target * 100.0
                remaining_target = required_protein_mass - base_protein_mass

                if remaining_pct <= 1e-9:
                    continue

                remaining_target_protein = remaining_target / remaining_pct
                if remaining_target_protein < low_protein - 1e-9 or remaining_target_protein > high_protein + 1e-9:
                    continue

                high_anchor_pct = remaining_pct * (remaining_target_protein - low_protein) / spread
                low_anchor_pct = remaining_pct - high_anchor_pct
                if high_anchor_pct < -1e-9 or low_anchor_pct < -1e-9:
                    continue

                fallback_mix = {i: floor_pct for i in ingredient_ids}
                fallback_mix[low_id] += max(0.0, low_anchor_pct)
                fallback_mix[high_id] += max(0.0, high_anchor_pct)
                return fallback_mix

            return None

        if target < minimum_achievable - 1e-9 or target > maximum_achievable + 1e-9:
            _raise_unreachable_target()

        # Full-participation optimizer: every selected ingredient keeps a
        # meaningful floor share, and the remaining mass is spread across ALL
        # ingredients (weighted toward abundant, lower-cost feeds) while the
        # blend is solved so weighted protein hits the target exactly.
        ingredient_ids = list(adjusted_percentages.keys())
        total_available_qty = sum(
            max(0.0, ingredient_lookup[i]["available_qty_kg"])
            for i in ingredient_ids
        )

        def _effective_cost(ingredient_id: int) -> float:
            base_cost = max(0.0, ingredient_lookup[ingredient_id]["cost_per_kg"])
            if total_available_qty <= 1e-9:
                return base_cost
            qty_ratio = ingredient_lookup[ingredient_id]["available_qty_kg"] / total_available_qty
            # Higher available quantity lowers effective cost, nudging share
            # toward abundant ingredients while still optimizing for cost.
            return base_cost / max(qty_ratio, 1e-6)

        def _preference_weight(ingredient_id: int) -> float:
            # Prefer feeds that are abundant in stock and cheap, but damp both
            # signals so no single feed can starve the others of share. Cost
            # of zero is treated as "unknown" (neutral) rather than "free".
            qty = max(0.0, ingredient_lookup[ingredient_id]["available_qty_kg"])
            cost = max(0.0, ingredient_lookup[ingredient_id]["cost_per_kg"])
            return (qty ** 0.5) / (1.0 + cost)

        def _solve_full_participation_mix(floor_pct: float) -> dict[int, float] | None:
            """Give every ingredient `floor_pct`, then distribute the remainder
            across all feeds with a single group-level scale factor solved so
            the mix hits the target protein exactly. Shares inside each group
            are equal (keeps the 2x2 solve well-conditioned); the preference
            for abundant feeds is expressed through the stock caps, which let
            plentiful ingredients absorb larger shares. Returns None when this
            floor cannot reach the target."""
            n = len(ingredient_ids)
            if n == 0 or floor_pct * n > 100.0 + 1e-9:
                return None

            remainder_pct = 100.0 - floor_pct * n
            floor_protein_mass = floor_pct * sum(protein_percent[i] for i in ingredient_ids)
            required_protein_mass = target * 100.0

            low_id = min(ingredient_ids, key=lambda i: protein_percent[i])
            high_id = max(ingredient_ids, key=lambda i: protein_percent[i])
            min_mix = (floor_protein_mass + remainder_pct * protein_percent[low_id]) / 100.0
            max_mix = (floor_protein_mass + remainder_pct * protein_percent[high_id]) / 100.0
            if target < min_mix - 1e-9 or target > max_mix + 1e-9:
                return None

            if remainder_pct <= 1e-9:
                if abs(floor_protein_mass - required_protein_mass) <= 1e-6:
                    return {i: floor_pct for i in ingredient_ids}
                return None

            required_remainder_protein = (required_protein_mass - floor_protein_mass) / remainder_pct

            high_group = {i for i in ingredient_ids if protein_percent[i] >= required_remainder_protein}
            low_group = set(ingredient_ids) - high_group

            if not high_group or not low_group:
                # Only exact when every feed has (nearly) the same protein.
                proteins = [protein_percent[i] for i in ingredient_ids]
                if max(proteins) - min(proteins) > 1e-9:
                    return None
                scale = remainder_pct / len(ingredient_ids)
                return {i: floor_pct + scale for i in ingredient_ids}

            # Equal weight per feed inside each group keeps the determinant of
            # the 2x2 group-scale solve well away from zero regardless of how
            # many feeds are selected.
            weights = {i: 1.0 for i in ingredient_ids}
            w_high = sum(weights[i] for i in high_group)
            w_low = sum(weights[i] for i in low_group)
            p_high = sum(weights[i] * protein_percent[i] for i in high_group)
            p_low = sum(weights[i] * protein_percent[i] for i in low_group)

            # Solve group scales alpha (high-protein group) and beta (low):
            #   alpha*w_high + beta*w_low = remainder_pct
            #   alpha*p_high + beta*p_low = required_remainder_protein * remainder_pct
            det = w_high * p_low - w_low * p_high
            if abs(det) <= 1e-12:
                return None
            alpha = remainder_pct * (p_low - required_remainder_protein * w_low) / det
            beta = remainder_pct * (w_high * required_remainder_protein - p_high) / det
            if alpha < -1e-9 or beta < -1e-9:
                return None
            alpha = max(alpha, 0.0)
            beta = max(beta, 0.0)

            mix = {}
            for i in ingredient_ids:
                extra = alpha * weights[i] if i in high_group else beta * weights[i]
                mix[i] = floor_pct + max(0.0, extra)

            # Absorb floating-point drift on the largest share so shares total 100.
            drift = 100.0 - sum(mix.values())
            if abs(drift) > 1e-9:
                anchor = max(mix, key=lambda i: mix[i])
                mix[anchor] = max(0.0, mix[anchor] + drift)
            return mix

        def _cap_mix_to_stock(mix: dict[int, float]) -> dict[int, float]:
            """Clip shares at stock caps and re-solve the two-group scales with
            capped items fixed at their cap, repeating until no share exceeds
            its cap. Returns None when the fixed caps make the target
            unreachable (i.e. stock is the binding constraint)."""
            mix = dict(mix)
            fixed: set[int] = set()
            for _ in range(len(ingredient_ids) + 2):
                newly_fixed = False
                for i in mix:
                    if i in fixed:
                        mix[i] = min(mix[i], stock_cap_pct[i])
                    elif mix[i] > stock_cap_pct[i] + 1e-9:
                        mix[i] = stock_cap_pct[i]
                        fixed.add(i)
                        newly_fixed = True
                if not newly_fixed:
                    break

                free_ids = [i for i in mix if i not in fixed]
                if not free_ids:
                    break
                fixed_pct = sum(mix[i] for i in fixed)
                fixed_protein = sum(mix[i] * protein_percent[i] for i in fixed)
                free_pct = 100.0 - fixed_pct
                if free_pct <= 1e-9:
                    break
                required_free_protein = (target * 100.0 - fixed_protein) / free_pct

                free_high = [i for i in free_ids if protein_percent[i] >= required_free_protein]
                free_low = [i for i in free_ids if protein_percent[i] < required_free_protein]
                if not free_high and free_low:
                    # No free feed sits above the required protein: put the
                    # richest free feed on the alpha side so its scale can
                    # grow while the rest shrink on beta.
                    richest = max(free_low, key=lambda i: protein_percent[i])
                    free_high = [richest]
                    free_low = [i for i in free_low if i != richest]
                if not free_high or not free_low:
                    proteins = [protein_percent[i] for i in free_ids]
                    if max(proteins) - min(proteins) > 1e-9:
                        return None
                    equal = free_pct / len(free_ids)
                    for i in free_ids:
                        mix[i] = equal
                    continue

                w_high = len(free_high)
                w_low = len(free_low)
                p_high = sum(protein_percent[i] for i in free_high)
                p_low = sum(protein_percent[i] for i in free_low)
                det = w_high * p_low - w_low * p_high
                if abs(det) <= 1e-12:
                    return None
                alpha = free_pct * (p_low - required_free_protein * w_low) / det
                beta = free_pct * (w_high * required_free_protein - p_high) / det
                if alpha < -1e-9 or beta < -1e-9:
                    return None
                alpha = max(alpha, 0.0)
                beta = max(beta, 0.0)
                for i in free_ids:
                    mix[i] = alpha if i in free_high else beta

            drift = 100.0 - sum(mix.values())
            if abs(drift) > 1e-9:
                flexible = [i for i in mix if i not in fixed and mix[i] < stock_cap_pct[i] - 1e-9]
                if flexible:
                    anchor = max(flexible, key=lambda i: mix[i])
                    mix[anchor] = max(0.0, mix[anchor] + drift)
            return mix

        def _mix_protein(mix: dict[int, float]) -> float:
            return sum(mix[i] * protein_percent[i] for i in mix) / 100.0

        def _max_protein_stock_mix() -> dict[int, float]:
            """Highest-protein mix that respects the stock caps: pour every feed
            up to its cap, protein-richest first. When the stock pool cannot
            fill 100% of the batch, shares are normalized up proportionally so
            the mix stays a valid 100%-total blend (and this is also the
            truthful maximum-protein composition for that case)."""
            by_protein = sorted(ingredient_ids, key=lambda i: -protein_percent[i])
            mix = {i: 0.0 for i in ingredient_ids}
            remaining = 100.0
            for i in by_protein:
                share = min(stock_cap_pct[i], remaining)
                mix[i] = share
                remaining -= share
                if remaining <= 1e-9:
                    break
            total_share = sum(mix.values())
            if total_share > 1e-9 and abs(total_share - 100.0) > 1e-9:
                # Under-pour: pool can't fill the batch -> proportional scale is
                # also the max-protein composition. Over-pour: numerical spill
                # from caps -> normalize back to a valid 100% blend.
                scale = 100.0 / total_share
                mix = {i: mix[i] * scale for i in ingredient_ids}
            return mix

        optimized_mix = None
        uncapped_mix = None
        for floor_pct in (5.0, 2.0, 1.0, 0.5, 0.1, 0.0):
            uncapped_mix = _solve_full_participation_mix(floor_pct)
            if uncapped_mix is None:
                continue
            candidate = _cap_mix_to_stock(uncapped_mix)
            if candidate is not None and _mix_protein(candidate) >= target - 0.05:
                optimized_mix = candidate
                break

        if optimized_mix is None:
            fallback = _build_fallback_feasible_mix()
            if fallback is not None:
                candidate = _cap_mix_to_stock(fallback)
                if candidate is not None and _mix_protein(candidate) >= target - 0.05:
                    optimized_mix = candidate
        if optimized_mix is None:
            max_mix = _max_protein_stock_mix()
            pool_fill_pct = sum(min(100.0, stock_cap_pct[i]) for i in ingredient_ids)
            if (
                pool_fill_pct >= 100.0 - 1e-9
                and _mix_protein(max_mix) + 0.05 >= target
            ):
                optimized_mix = max_mix
            else:
                exc = FormulationInfeasibleError(
                    (
                        f"Not enough stock of higher-protein feeds to reach {target:g}% protein "
                        f"for a {float(batch_size_kg):g} kg batch with the selected feeds. "
                        f"Reduce the batch size or restock the limiting items."
                    ),
                    target_protein_percent=target,
                    minimum_achievable_protein_percent=minimum_achievable,
                    maximum_achievable_protein_percent=maximum_achievable,
                )
                limiting = [
                    {
                        "ingredient_id": i,
                        "name": ingredient_lookup[i]["name"],
                        "protein_grams_per_kg": ingredient_lookup[i]["protein_per_kg"],
                        "available_quantity_kg": round(float(ingredient_lookup[i]["available_qty_kg"]), 4),
                    }
                    for i in ingredient_ids
                    if protein_percent[i] > target and stock_cap_pct[i] < 100.0 - 1e-9
                ]
                if not limiting:
                    # Whole stock pool is the constraint (or no feed beats the
                    # target): report everything that ran short.
                    limiting = [
                        {
                            "ingredient_id": i,
                            "name": ingredient_lookup[i]["name"],
                            "protein_grams_per_kg": ingredient_lookup[i]["protein_per_kg"],
                            "available_quantity_kg": round(float(ingredient_lookup[i]["available_qty_kg"]), 4),
                        }
                        for i in ingredient_ids
                        if stock_cap_pct[i] < 100.0 - 1e-9
                    ]
                exc.limiting_ingredients = limiting
                exc.max_feasible_mix = [
                    {
                        "ingredient_id": i,
                        "name": ingredient_lookup[i]["name"],
                        "percentage": round(max_mix[i], 4),
                        "weight_kg": round(max_mix[i] * float(batch_size_kg) / 100.0, 4),
                        "protein_grams_per_kg": ingredient_lookup[i]["protein_per_kg"],
                    }
                    for i in ingredient_ids
                    if max_mix[i] > 1e-9
                ]
                raise exc

        participation_warning = None
        zero_share_ids = [i for i, share in (uncapped_mix or optimized_mix).items() if share <= 1e-9]
        if zero_share_ids and len(ingredient_ids) > 1:
            zero_names = [ingredient_lookup[i]["name"] for i in zero_share_ids]
            participation_warning = (
                f"The {target:g}% protein target is at the edge of what the selected feeds can "
                f"reach, so these feeds had to be left out of the mix: {', '.join(zero_names)}. "
                "Add a higher-protein feed or lower the protein "
                "goal to blend every selected feed."
            )

        adjusted_percentages = optimized_mix

        adjusted_ingredients = []
        for ing in base_ingredients:
            ing_id = ing["ingredient_id"]
            current_pct = float(ing["percentage"])
            adjusted_pct = adjusted_percentages[ing_id]
            adjusted_ingredients.append({
                "ingredient_id": ing_id,
                "name": ingredient_lookup[ing_id]["name"],
                "current_percentage": round(current_pct, 4),
                "adjusted_percentage": round(adjusted_pct, 4),
                "adjustment": round(adjusted_pct - current_pct, 4),
                "protein_grams_per_kg": ingredient_lookup[ing_id]["protein_per_kg"],
                "cost_per_kg": round(float(ingredient_lookup[ing_id]["cost_per_kg"]), 4),
                "available_quantity_kg": round(float(ingredient_lookup[ing_id]["available_qty_kg"]), 4),
            })

        # Project nutrition with adjusted ingredients
        adjusted_ingredient_list = [
            {"ingredient_id": ing["ingredient_id"], "percentage": ing["adjusted_percentage"]}
            for ing in adjusted_ingredients
        ]
        projected = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg,
            adjusted_ingredient_list,
            tenant_id=tenant_id,
        )

        projected_protein = sum(
            adjusted_percentages[ingredient_id] * protein_percent[ingredient_id] / 100.0
            for ingredient_id in adjusted_percentages
        )
        if adjustment_needed > 0 and projected_protein + 1e-6 < target:
            fallback_mix = _build_fallback_feasible_mix()
            if fallback_mix is None:
                _raise_unreachable_target()
            adjusted_percentages = fallback_mix
            adjusted_ingredients = []
            for ing in base_ingredients:
                ing_id = ing["ingredient_id"]
                current_pct = float(ing["percentage"])
                adjusted_pct = adjusted_percentages[ing_id]
                adjusted_ingredients.append({
                    "ingredient_id": ing_id,
                    "name": ingredient_lookup[ing_id]["name"],
                    "current_percentage": round(current_pct, 4),
                    "adjusted_percentage": round(adjusted_pct, 4),
                    "adjustment": round(adjusted_pct - current_pct, 4),
                    "protein_grams_per_kg": ingredient_lookup[ing_id]["protein_per_kg"],
                })
            adjusted_ingredient_list = [
                {"ingredient_id": ing["ingredient_id"], "percentage": ing["adjusted_percentage"]}
                for ing in adjusted_ingredients
            ]
            projected = RecipeFormulationService.calculate_batch_protein_content(
                batch_size_kg,
                adjusted_ingredient_list,
                tenant_id=tenant_id,
            )

        projected_cost_per_kg = sum(
            adjusted_percentages[ingredient_id] * ingredient_lookup[ingredient_id]["cost_per_kg"] / 100.0
            for ingredient_id in adjusted_percentages
        )
        projected_total_cost = projected_cost_per_kg * float(batch_size_kg)

        return {
            "current_protein_percent": round(current_protein, 2),
            "target_protein_percent": target_protein_percent,
            "feeding_group": normalized_feeding_group,
            "recipe_type": normalized_recipe_type,
            "adjustment_needed": round(adjustment_needed, 2),
            "adjusted_ingredients": adjusted_ingredients,
            "projected_nutrition": projected,
            "projected_cost": {
                "cost_per_kg": round(projected_cost_per_kg, 4),
                "total_cost": round(projected_total_cost, 2),
            },
            "participation_warning": participation_warning,
            "adjustment_strategy": (
                f"Blended every selected feed to meet the {target:g}% protein target, "
                f"giving each ingredient a minimum share and weighting the rest toward "
                f"abundant, lower-cost feeds "
                f"(projected protein {round(projected['average_protein_percent'], 2)}%)."
            ),
        }

    @staticmethod
    def save_recipe_from_formulation(
        tenant_id: int,
        recipe_name: str,
        batch_size_kg: float,
        adjusted_ingredients: list[dict],  # [{"ingredient_id": int, "percentage": float}, ...]
        target_protein_percent: float,
        recipe_type: str | None = None,
        feeding_group: str | None = None,
        measurement_settings: dict | None = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """
        Save a formulated recipe to the database.
        Mark it as 'adopted' for the herd.

        Returns saved recipe with ID and status.
        """
        try:
            ingredient_lookup = RecipeFormulationService._validate_recipe_ingredients(
                tenant_id,
                adjusted_ingredients,
            )
            normalized_feeding_group = FeedingGroupRecipePolicyService.normalize_feeding_group(feeding_group)
            normalized_recipe_type = FeedingGroupRecipePolicyService.resolve_recipe_type(
                feeding_group=normalized_feeding_group,
                requested_recipe_type=recipe_type,
            )
            settings = measurement_settings or {
                'quantity_basis': 'concentrate' if normalized_recipe_type == 'dairy_meal' else 'total_ration',
                'concentrate_kg_per_head_day': None,
                'bulk_density_kg_per_litre': None,
                'bucket_volume_litres': None,
                'scoop_weight_kg': None,
            }
            ingredient_ids = [int(ing_data["ingredient_id"]) for ing_data in adjusted_ingredients]
            _, missing_ids, ineligible_ids = FeedMixerPolicyService.validate_items_for_recipe_type(
                tenant_id=tenant_id,
                ingredient_ids=ingredient_ids,
                recipe_type=normalized_recipe_type,
            )
            if missing_ids:
                raise ValueError(f"Ingredient(s) not found for tenant: {missing_ids}.")
            if ineligible_ids:
                raise ValueError(
                    f"Ingredient(s) not eligible for recipe_type {normalized_recipe_type}: {ineligible_ids}."
                )

            # Upsert by (tenant, name, type): re-saving a mix updates the
            # existing recipe in place instead of piling up duplicate rows.
            recipe = FeedRecipe.query.filter_by(
                tenant_id=tenant_id,
                recipe_name=recipe_name,
                recipe_type=normalized_recipe_type,
            ).first()
            if recipe is not None:
                recipe.target_protein_percentage = target_protein_percent
                recipe.is_active = True
                for field, value in settings.items():
                    setattr(recipe, field, value)
                RecipeIngredient.query.filter_by(
                    tenant_id=tenant_id, recipe_id=recipe.id
                ).delete()
                db.session.flush()
            else:
                recipe = FeedRecipe(
                    tenant_id=tenant_id,
                    recipe_name=recipe_name,
                    target_protein_percentage=target_protein_percent,
                    recipe_type=normalized_recipe_type,
                    feeding_group=normalized_feeding_group,
                    **settings,
                    is_active=True,  # Auto-adopt the recipe
                    created_by=user_id,
                )
                db.session.add(recipe)
                db.session.flush()

            if recipe is not None:
                recipe.feeding_group = normalized_feeding_group

            # Add ingredients
            for ing_data in adjusted_ingredients:
                ingredient_id = ing_data["ingredient_id"]
                percentage = ing_data["percentage"]

                # Verify ingredient exists
                ingredient = ingredient_lookup[ingredient_id]

                recipe_ing = RecipeIngredient(
                    tenant_id=tenant_id,
                    recipe_id=recipe.id,
                    inventory_item_id=ingredient_id,
                    inclusion_percentage=Decimal(str(percentage)),
                )
                db.session.add(recipe_ing)

            db.session.commit()

            # Calculate final nutrition
            nutrition = RecipeFormulationService.calculate_batch_protein_content(
                batch_size_kg,
                adjusted_ingredients,
                tenant_id=tenant_id,
            )

            return {
                "recipe_id": recipe.id,
                "recipe_name": recipe_name,
                "target_protein_percent": target_protein_percent,
                "feeding_group": normalized_feeding_group,
                "recipe_type": normalized_recipe_type,
                "achieved_protein_percent": nutrition["average_protein_percent"],
                "batch_size_kg": batch_size_kg,
                "status": "ADOPTED",
                "message": f"Recipe '{recipe_name}' has been formulated and adopted for the herd.",
                "nutrition_summary": nutrition,
            }

        except ValueError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to save recipe: {str(e)}")

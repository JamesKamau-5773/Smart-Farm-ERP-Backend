from __future__ import annotations
"""
Service for recipe formulation with protein targeting.
Single Responsibility: Calculate and adjust ingredient percentages to hit target protein levels.
"""
from decimal import Decimal
from typing import Optional

from app import db
from app.models.supply import InventoryItem, FeedRecipe, RecipeIngredient
from app.services.feed_mixer_policy_service import FeedMixerPolicyService
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


class RecipeFormulationService:
    """Handles recipe creation with automatic protein targeting and ingredient adjustment."""

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
        ingredients_with_percentages: list[dict]  # [{"ingredient_id": int, "percentage": float}, ...]
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
            ingredient = InventoryItem.query.filter_by(id=ingredient_id).first()
            if not ingredient:
                raise ValueError(f"Ingredient {ingredient_id} not found.")

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
        requested_recipe_type = FeedMixerPolicyService.normalize_recipe_type(
            recipe_type,
            default=None,
        )
        normalized_recipe_type = requested_recipe_type or FeedMixerPolicyService.MAIN_MEAL
        if requested_recipe_type is not None:
            ingredient_ids = [int(ing["ingredient_id"]) for ing in base_ingredients]
            _, missing_ids, ineligible_ids = FeedMixerPolicyService.validate_items_for_recipe_type(
                tenant_id=tenant_id,
                ingredient_ids=ingredient_ids,
                recipe_type=requested_recipe_type,
            )
            if missing_ids:
                raise ValueError(f"Ingredient(s) not found for tenant: {missing_ids}.")
            if ineligible_ids:
                raise ValueError(
                    f"Ingredient(s) not eligible for recipe_type {requested_recipe_type}: {ineligible_ids}."
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
            base_ingredients
        )
        current_protein = current["average_protein_percent"]

        # Calculate adjustment needed
        adjustment_needed = target_protein_percent - current_protein

        if abs(adjustment_needed) < 1e-6:
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

        # Cost-and-quantity aware optimizer:
        # 1) keep a small floor share when feasible so all ingredients can
        #    participate, 2) solve the remaining blend with the cheapest
        #    effective-cost protein pair spanning the target.
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

        optimized_mix = None
        for floor_pct in (1.0, 0.5, 0.1, 0.0):
            if floor_pct * len(ingredient_ids) > 100.0 + 1e-9:
                continue

            remainder_pct = 100.0 - floor_pct * len(ingredient_ids)
            if remainder_pct < -1e-9:
                continue

            protein_mass_floor = floor_pct * sum(protein_percent[i] for i in ingredient_ids)
            required_total_protein_mass = target * 100.0
            remaining_required_mass = required_total_protein_mass - protein_mass_floor

            if remainder_pct <= 1e-9:
                if abs(remaining_required_mass) <= 1e-6:
                    optimized_mix = {i: floor_pct for i in ingredient_ids}
                    break
                continue

            target_remainder_protein = remaining_required_mass / remainder_pct

            best_pair = None
            for low_id in ingredient_ids:
                for high_id in ingredient_ids:
                    if low_id == high_id:
                        continue
                    low_protein = protein_percent[low_id]
                    high_protein = protein_percent[high_id]
                    spread = high_protein - low_protein
                    if spread <= 1e-9:
                        continue
                    if target_remainder_protein < low_protein - 1e-9 or target_remainder_protein > high_protein + 1e-9:
                        continue

                    high_weight = (target_remainder_protein - low_protein) / spread
                    low_weight = 1.0 - high_weight
                    if low_weight < -1e-9 or high_weight < -1e-9:
                        continue

                    pair_effective_cost = (
                        low_weight * _effective_cost(low_id)
                        + high_weight * _effective_cost(high_id)
                    )
                    pair_cost = (
                        low_weight * ingredient_lookup[low_id]["cost_per_kg"]
                        + high_weight * ingredient_lookup[high_id]["cost_per_kg"]
                    )

                    candidate = (
                        pair_effective_cost,
                        pair_cost,
                        -(
                            ingredient_lookup[low_id]["available_qty_kg"]
                            + ingredient_lookup[high_id]["available_qty_kg"]
                        ),
                        low_id,
                        high_id,
                        low_weight,
                        high_weight,
                    )

                    if best_pair is None or candidate < best_pair:
                        best_pair = candidate

            if best_pair is None:
                continue

            _, _, _, low_id, high_id, low_weight, high_weight = best_pair
            optimized_mix = {i: floor_pct for i in ingredient_ids}
            optimized_mix[low_id] += max(0.0, remainder_pct * low_weight)
            optimized_mix[high_id] += max(0.0, remainder_pct * high_weight)
            break

        if optimized_mix is None:
            optimized_mix = _build_fallback_feasible_mix()
        if optimized_mix is None:
            _raise_unreachable_target()

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
            adjusted_ingredient_list
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
                adjusted_ingredient_list
            )

        projected_cost_per_kg = sum(
            adjusted_percentages[ingredient_id] * ingredient_lookup[ingredient_id]["cost_per_kg"] / 100.0
            for ingredient_id in adjusted_percentages
        )
        projected_total_cost = projected_cost_per_kg * float(batch_size_kg)

        return {
            "current_protein_percent": round(current_protein, 2),
            "target_protein_percent": target_protein_percent,
            "recipe_type": normalized_recipe_type,
            "adjustment_needed": round(adjustment_needed, 2),
            "adjusted_ingredients": adjusted_ingredients,
            "projected_nutrition": projected,
            "projected_cost": {
                "cost_per_kg": round(projected_cost_per_kg, 4),
                "total_cost": round(projected_total_cost, 2),
            },
            "adjustment_strategy": (
                f"Optimized ingredient inclusion to meet the {target:g}% protein target "
                f"at lower effective cost, prioritizing higher-quantity and lower-cost feeds "
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
        user_id: Optional[int] = None,
        yield_target_id: Optional[int] = None,
    ) -> dict:
        """
        Save a formulated recipe to the database.
        Mark it as 'adopted' for the herd.
        
        Returns saved recipe with ID and status.
        """
        try:
            requested_recipe_type = FeedMixerPolicyService.normalize_recipe_type(
                recipe_type,
                default=None,
            )
            normalized_recipe_type = requested_recipe_type or FeedMixerPolicyService.MAIN_MEAL
            if requested_recipe_type is not None:
                ingredient_ids = [int(ing_data["ingredient_id"]) for ing_data in adjusted_ingredients]
                _, missing_ids, ineligible_ids = FeedMixerPolicyService.validate_items_for_recipe_type(
                    tenant_id=tenant_id,
                    ingredient_ids=ingredient_ids,
                    recipe_type=requested_recipe_type,
                )
                if missing_ids:
                    raise ValueError(f"Ingredient(s) not found for tenant: {missing_ids}.")
                if ineligible_ids:
                    raise ValueError(
                        f"Ingredient(s) not eligible for recipe_type {requested_recipe_type}: {ineligible_ids}."
                    )

            # Create recipe
            recipe = FeedRecipe(
                tenant_id=tenant_id,
                recipe_name=recipe_name,
                target_protein_percentage=target_protein_percent,
                recipe_type=normalized_recipe_type,
                is_active=True,  # Auto-adopt the recipe
                created_by=user_id,
            )
            db.session.add(recipe)
            db.session.flush()

            # Add ingredients
            for ing_data in adjusted_ingredients:
                ingredient_id = ing_data["ingredient_id"]
                percentage = ing_data["percentage"]

                # Verify ingredient exists
                ingredient = InventoryItem.query.filter_by(id=ingredient_id, tenant_id=tenant_id).first()
                if not ingredient:
                    raise ValueError(f"Ingredient {ingredient_id} not found for this tenant.")

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
                adjusted_ingredients
            )

            return {
                "recipe_id": recipe.id,
                "recipe_name": recipe_name,
                "target_protein_percent": target_protein_percent,
                "recipe_type": normalized_recipe_type,
                "achieved_protein_percent": nutrition["average_protein_percent"],
                "batch_size_kg": batch_size_kg,
                "status": "ADOPTED",
                "message": f"Recipe '{recipe_name}' has been formulated and adopted for the herd.",
                "nutrition_summary": nutrition,
            }

        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to save recipe: {str(e)}")

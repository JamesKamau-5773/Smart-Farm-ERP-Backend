from __future__ import annotations
"""
Service for recipe formulation with protein targeting.
Single Responsibility: Calculate and adjust ingredient percentages to hit target protein levels.
"""
from decimal import Decimal
from typing import Optional

from app import db
from app.models.supply import InventoryItem, FeedRecipe, FormulaIngredient
from app.repositories.cow_repo import CowRepository


class RecipeFormulationService:
    """Handles recipe creation with automatic protein targeting and ingredient adjustment."""

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
            "average_protein_percent": round(average_protein_percent, 2),
        }

    @staticmethod
    def suggest_ingredient_adjustments(
        tenant_id: int,
        batch_size_kg: float,
        base_ingredients: list[dict],  # [{"ingredient_id": int, "percentage": float}, ...]
        target_protein_percent: float,
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
        # Get current nutrition profile
        current = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg,
            base_ingredients
        )
        current_protein = current["average_protein_percent"]

        # Calculate adjustment needed
        adjustment_needed = target_protein_percent - current_protein

        if abs(adjustment_needed) < 0.1:
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

        # Strategy 1: Adjust high-protein ingredients up/down proportionally
        # Identify high-protein and low-protein ingredients
        high_protein_ings = []
        low_protein_ings = []
        neutral_ings = []

        ingredient_lookup = {}
        for ing in base_ingredients:
            ing_obj = InventoryItem.query.filter_by(id=ing["ingredient_id"]).first()
            protein = float(ing_obj.protein_grams_per_kg) if ing_obj else 0
            ingredient_lookup[ing["ingredient_id"]] = {
                "protein_per_kg": protein,
                "name": ing_obj.name if ing_obj else f"Ingredient {ing['ingredient_id']}",
                "current_pct": ing["percentage"],
            }

            if protein > 200:  # Rough threshold for high-protein
                high_protein_ings.append(ing["ingredient_id"])
            elif protein < 100:
                low_protein_ings.append(ing["ingredient_id"])
            else:
                neutral_ings.append(ing["ingredient_id"])

        # Proportional adjustment
        adjusted_ingredients = []
        adjustment_multiplier = 1.0

        if adjustment_needed > 0 and high_protein_ings:
            # Need more protein: increase high-protein ingredients
            adjustment_multiplier = (current_protein + adjustment_needed) / current_protein if current_protein > 0 else 1.1
        elif adjustment_needed < 0 and low_protein_ings:
            # Need less protein: increase low-protein ingredients
            adjustment_multiplier = (current_protein + adjustment_needed) / current_protein if current_protein > 0 else 0.9

        for ing in base_ingredients:
            ing_id = ing["ingredient_id"]
            current_pct = ing["percentage"]
            protein_per_kg = ingredient_lookup[ing_id]["protein_per_kg"]

            # Apply adjustment multiplier
            if adjustment_needed > 0:
                # Increase high-protein ingredients
                if ing_id in high_protein_ings:
                    adjusted_pct = current_pct * (1 + (adjustment_needed / 100))
                else:
                    adjusted_pct = current_pct * (1 - (adjustment_needed / 200))
            else:
                # Increase low-protein ingredients
                if ing_id in low_protein_ings:
                    adjusted_pct = current_pct * (1 + abs(adjustment_needed / 100))
                else:
                    adjusted_pct = current_pct * (1 - abs(adjustment_needed / 200))

            adjusted_pct = max(0, min(100, adjusted_pct))  # Clamp to 0-100

            adjusted_ingredients.append({
                "ingredient_id": ing_id,
                "name": ingredient_lookup[ing_id]["name"],
                "current_percentage": round(current_pct, 2),
                "adjusted_percentage": round(adjusted_pct, 2),
                "adjustment": round(adjusted_pct - current_pct, 2),
                "protein_grams_per_kg": protein_per_kg,
            })

        # Normalize percentages to sum to 100
        total_pct = sum(ing["adjusted_percentage"] for ing in adjusted_ingredients)
        if total_pct > 0:
            adjusted_ingredients = [
                {
                    **ing,
                    "adjusted_percentage": round((ing["adjusted_percentage"] / total_pct) * 100, 2),
                }
                for ing in adjusted_ingredients
            ]

        # Project nutrition with adjusted ingredients
        adjusted_ingredient_list = [
            {"ingredient_id": ing["ingredient_id"], "percentage": ing["adjusted_percentage"]}
            for ing in adjusted_ingredients
        ]
        projected = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg,
            adjusted_ingredient_list
        )

        return {
            "current_protein_percent": round(current_protein, 2),
            "target_protein_percent": target_protein_percent,
            "adjustment_needed": round(adjustment_needed, 2),
            "adjusted_ingredients": adjusted_ingredients,
            "projected_nutrition": projected,
            "adjustment_strategy": f"Adjusted high/low protein ingredients to shift from {round(current_protein, 1)}% to {round(projected['average_protein_percent'], 1)}% protein.",
        }

    @staticmethod
    def save_recipe_from_formulation(
        tenant_id: int,
        recipe_name: str,
        batch_size_kg: float,
        adjusted_ingredients: list[dict],  # [{"ingredient_id": int, "percentage": float}, ...]
        target_protein_percent: float,
        user_id: Optional[int] = None,
        yield_target_id: Optional[int] = None,
    ) -> dict:
        """
        Save a formulated recipe to the database.
        Mark it as 'adopted' for the herd.
        
        Returns saved recipe with ID and status.
        """
        try:
            # Create recipe
            recipe = FeedRecipe(
                tenant_id=tenant_id,
                recipe_name=recipe_name,
                target_protein_percentage=target_protein_percent,
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

                formula_ing = FormulaIngredient(
                    tenant_id=tenant_id,
                    recipe_id=recipe.id,
                    inventory_item_id=ingredient_id,
                    inclusion_percentage=Decimal(str(percentage)),
                )
                db.session.add(formula_ing)

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
                "achieved_protein_percent": nutrition["average_protein_percent"],
                "batch_size_kg": batch_size_kg,
                "status": "ADOPTED",
                "message": f"Recipe '{recipe_name}' has been formulated and adopted for the herd.",
                "nutrition_summary": nutrition,
            }

        except Exception as e:
            db.session.rollback()
            raise Exception(f"Failed to save recipe: {str(e)}")

"""
Test suite for RecipeFormulationService.
Tests protein calculation, ingredient adjustment, and recipe auto-save functionality.
"""
from __future__ import annotations
import pytest
from decimal import Decimal
from tests.base import BaseTestCase
from app.services.recipe_formulation_service import RecipeFormulationService
from app.models.supply import InventoryItem, FeedRecipe, FormulaIngredient
from app import db


class TestRecipeFormulationService(BaseTestCase):
    """Test recipe formulation with protein targeting."""

    def setUp(self):
        """Set up test ingredients with known protein content."""
        super().setUp()
        
        # Create test ingredients
        self.maize_germ = InventoryItem(
            tenant_id=self.tenant_id,
            name="Maize Germ",
            protein_grams_per_kg=Decimal("120"),
            energy_mj_per_kg=Decimal("14.5"),
            fiber_grams_per_kg=Decimal("50"),
            cost_per_kg=Decimal("25.00"),
        )
        
        self.wheat_bran = InventoryItem(
            tenant_id=self.tenant_id,
            name="Wheat Bran",
            protein_grams_per_kg=Decimal("80"),
            energy_mj_per_kg=Decimal("12.0"),
            fiber_grams_per_kg=Decimal("100"),
            cost_per_kg=Decimal("15.00"),
        )
        
        self.sunflower_cake = InventoryItem(
            tenant_id=self.tenant_id,
            name="Sunflower Cake",
            protein_grams_per_kg=Decimal("200"),
            energy_mj_per_kg=Decimal("13.0"),
            fiber_grams_per_kg=Decimal("80"),
            cost_per_kg=Decimal("35.00"),
        )
        
        db.session.add_all([self.maize_germ, self.wheat_bran, self.sunflower_cake])
        db.session.commit()

    def test_get_ingredient_nutrition_profile_success(self):
        """Test retrieving nutrition profile of an ingredient."""
        profile = RecipeFormulationService.get_ingredient_nutrition_profile(
            ingredient_id=self.maize_germ.id,
            tenant_id=self.tenant_id
        )
        
        assert profile["ingredient_id"] == self.maize_germ.id
        assert profile["name"] == "Maize Germ"
        assert profile["protein_grams_per_kg"] == 120.0
        assert profile["energy_mj_per_kg"] == 14.5
        assert profile["fiber_grams_per_kg"] == 50.0

    def test_get_ingredient_nutrition_profile_not_found(self):
        """Test retrieving nutrition profile of non-existent ingredient."""
        with pytest.raises(ValueError) as exc_info:
            RecipeFormulationService.get_ingredient_nutrition_profile(
                ingredient_id=9999,
                tenant_id=self.tenant_id
            )
        assert "not found" in str(exc_info.value)

    def test_calculate_batch_protein_content_simple(self):
        """Test basic protein calculation for a batch."""
        result = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg=500,
            ingredients_with_percentages=[
                {"ingredient_id": self.maize_germ.id, "percentage": 50},
                {"ingredient_id": self.wheat_bran.id, "percentage": 30},
                {"ingredient_id": self.sunflower_cake.id, "percentage": 20},
            ]
        )
        
        assert result["batch_size_kg"] == 500
        assert len(result["ingredients"]) == 3
        
        # Verify weights
        assert result["ingredients"][0]["weight_kg"] == 250  # 50% of 500
        assert result["ingredients"][1]["weight_kg"] == 150  # 30% of 500
        assert result["ingredients"][2]["weight_kg"] == 100  # 20% of 500
        
        # Verify total protein
        # Maize: 250 kg * 120 g/kg = 30,000g
        # Wheat: 150 kg * 80 g/kg = 12,000g
        # Sunflower: 100 kg * 200 g/kg = 20,000g
        # Total: 62,000g
        assert result["total_protein_grams"] == 62000
        
        # Protein %: (62000 / (500 * 1000)) * 100 = 12.4%
        assert result["average_protein_percent"] == 12.4

    def test_calculate_batch_protein_content_high_protein_mix(self):
        """Test calculation with high-protein ingredient dominant."""
        result = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg=500,
            ingredients_with_percentages=[
                {"ingredient_id": self.sunflower_cake.id, "percentage": 100},  # 200 g/kg protein
            ]
        )
        
        assert result["average_protein_percent"] == 20.0  # (200 / 1000) * 100

    def test_calculate_batch_protein_content_low_protein_mix(self):
        """Test calculation with low-protein ingredient."""
        result = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg=500,
            ingredients_with_percentages=[
                {"ingredient_id": self.wheat_bran.id, "percentage": 100},  # 80 g/kg protein
            ]
        )
        
        assert result["average_protein_percent"] == 8.0  # (80 / 1000) * 100

    def test_suggest_ingredient_adjustments_no_adjustment_needed(self):
        """Test suggestions when target is already achieved."""
        # Start with mix that achieves 12.4% protein
        base_ingredients = [
            {"ingredient_id": self.maize_germ.id, "percentage": 50},
            {"ingredient_id": self.wheat_bran.id, "percentage": 30},
            {"ingredient_id": self.sunflower_cake.id, "percentage": 20},
        ]
        
        # Request target of 12.4% (already achieved)
        result = RecipeFormulationService.suggest_ingredient_adjustments(
            tenant_id=self.tenant_id,
            batch_size_kg=500,
            base_ingredients=base_ingredients,
            target_protein_percent=12.4,
        )
        
        assert result["current_protein_percent"] == 12.4
        assert result["target_protein_percent"] == 12.4
        assert result["adjustment_needed"] == 0
        assert "No adjustment needed" in result["adjustment_strategy"]

    def test_suggest_ingredient_adjustments_increase_protein(self):
        """Test suggestions when need to increase protein."""
        base_ingredients = [
            {"ingredient_id": self.maize_germ.id, "percentage": 50},
            {"ingredient_id": self.wheat_bran.id, "percentage": 30},
            {"ingredient_id": self.sunflower_cake.id, "percentage": 20},
        ]
        
        result = RecipeFormulationService.suggest_ingredient_adjustments(
            tenant_id=self.tenant_id,
            batch_size_kg=500,
            base_ingredients=base_ingredients,
            target_protein_percent=16.5,
        )
        
        assert result["current_protein_percent"] == 12.4
        assert result["target_protein_percent"] == 16.5
        assert result["adjustment_needed"] == 4.1
        
        # Should increase sunflower (high protein) and decrease others
        sunflower_adjustment = result["adjusted_ingredients"][2]
        assert sunflower_adjustment["adjustment"] > 0
        
        # Verify projected nutrition is close to target
        assert abs(result["projected_nutrition"]["average_protein_percent"] - 16.5) < 1.0

    def test_suggest_ingredient_adjustments_decrease_protein(self):
        """Test suggestions when need to decrease protein."""
        base_ingredients = [
            {"ingredient_id": self.sunflower_cake.id, "percentage": 100},  # 20% protein
        ]
        
        result = RecipeFormulationService.suggest_ingredient_adjustments(
            tenant_id=self.tenant_id,
            batch_size_kg=500,
            base_ingredients=base_ingredients,
            target_protein_percent=12.0,
        )
        
        assert result["current_protein_percent"] == 20.0
        assert result["adjustment_needed"] < 0
        
        # Projected should be lower than current
        assert result["projected_nutrition"]["average_protein_percent"] < result["current_protein_percent"]

    def test_save_recipe_from_formulation_success(self):
        """Test saving formulated recipe to database."""
        result = RecipeFormulationService.save_recipe_from_formulation(
            tenant_id=self.tenant_id,
            recipe_name="Test Recipe - 16.5% Protein",
            batch_size_kg=500,
            adjusted_ingredients=[
                {"ingredient_id": self.maize_germ.id, "percentage": 35},
                {"ingredient_id": self.wheat_bran.id, "percentage": 25},
                {"ingredient_id": self.sunflower_cake.id, "percentage": 40},
            ],
            target_protein_percent=16.5,
            user_id=self.user_id,
        )
        
        assert result["recipe_id"] is not None
        assert result["recipe_name"] == "Test Recipe - 16.5% Protein"
        assert result["target_protein_percent"] == 16.5
        assert result["status"] == "ADOPTED"
        assert "formulated and adopted" in result["message"]
        
        # Verify recipe was saved to database
        saved_recipe = FeedRecipe.query.filter_by(id=result["recipe_id"]).first()
        assert saved_recipe is not None
        assert saved_recipe.tenant_id == self.tenant_id
        assert saved_recipe.is_active is True
        
        # Verify ingredients were saved
        ingredients = FormulaIngredient.query.filter_by(recipe_id=saved_recipe.id).all()
        assert len(ingredients) == 3
        
        # Verify percentages
        ingredient_map = {ing.inventory_item_id: ing.inclusion_percentage for ing in ingredients}
        assert ingredient_map[self.maize_germ.id] == Decimal("35")
        assert ingredient_map[self.wheat_bran.id] == Decimal("25")
        assert ingredient_map[self.sunflower_cake.id] == Decimal("40")

    def test_save_recipe_from_formulation_invalid_ingredient(self):
        """Test saving recipe with non-existent ingredient."""
        with pytest.raises(ValueError) as exc_info:
            RecipeFormulationService.save_recipe_from_formulation(
                tenant_id=self.tenant_id,
                recipe_name="Test Recipe",
                batch_size_kg=500,
                adjusted_ingredients=[
                    {"ingredient_id": 9999, "percentage": 100},  # Non-existent
                ],
                target_protein_percent=16.5,
                user_id=self.user_id,
            )
        assert "not found" in str(exc_info.value)

    def test_save_recipe_with_yield_target_id(self):
        """Test saving recipe with link to Milk Lab yield target."""
        result = RecipeFormulationService.save_recipe_from_formulation(
            tenant_id=self.tenant_id,
            recipe_name="Herd Target 4.3L - 16.5% Protein",
            batch_size_kg=500,
            adjusted_ingredients=[
                {"ingredient_id": self.maize_germ.id, "percentage": 35},
                {"ingredient_id": self.wheat_bran.id, "percentage": 25},
                {"ingredient_id": self.sunflower_cake.id, "percentage": 40},
            ],
            target_protein_percent=16.5,
            user_id=self.user_id,
            yield_target_id=123,
        )
        
        # Verify recipe was created (yield_target_id is stored for audit trail)
        assert result["status"] == "ADOPTED"
        saved_recipe = FeedRecipe.query.filter_by(id=result["recipe_id"]).first()
        assert saved_recipe is not None

    def test_complete_workflow_milk_lab_integration(self):
        """Test complete workflow: calculate → adjust → save."""
        
        # Step 1: Get current nutrition
        current = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg=500,
            ingredients_with_percentages=[
                {"ingredient_id": self.maize_germ.id, "percentage": 50},
                {"ingredient_id": self.wheat_bran.id, "percentage": 30},
                {"ingredient_id": self.sunflower_cake.id, "percentage": 20},
            ]
        )
        assert current["average_protein_percent"] == 12.4
        
        # Step 2: Get adjustment suggestions
        suggestions = RecipeFormulationService.suggest_ingredient_adjustments(
            tenant_id=self.tenant_id,
            batch_size_kg=500,
            base_ingredients=[
                {"ingredient_id": self.maize_germ.id, "percentage": 50},
                {"ingredient_id": self.wheat_bran.id, "percentage": 30},
                {"ingredient_id": self.sunflower_cake.id, "percentage": 20},
            ],
            target_protein_percent=16.5,
        )
        assert suggestions["current_protein_percent"] == 12.4
        assert suggestions["target_protein_percent"] == 16.5
        
        # Step 3: Save recipe with adjusted ingredients
        recipe_result = RecipeFormulationService.save_recipe_from_formulation(
            tenant_id=self.tenant_id,
            recipe_name="Herd Target 4.3L - 16.5% Protein",
            batch_size_kg=500,
            adjusted_ingredients=[
                ing for ing in suggestions["adjusted_ingredients"]
            ],
            target_protein_percent=16.5,
            user_id=self.user_id,
        )
        
        assert recipe_result["status"] == "ADOPTED"
        assert recipe_result["achieved_protein_percent"] >= 16.0  # Allow small margin
        
        # Verify recipe persisted
        saved_recipe = FeedRecipe.query.filter_by(id=recipe_result["recipe_id"]).first()
        assert saved_recipe is not None
        assert saved_recipe.is_active is True


class TestRecipeFormulationEdgeCases(BaseTestCase):
    """Test edge cases and error conditions."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        
        self.ingredient = InventoryItem(
            tenant_id=self.tenant_id,
            name="Test Ingredient",
            protein_grams_per_kg=Decimal("100"),
            energy_mj_per_kg=Decimal("10.0"),
            fiber_grams_per_kg=Decimal("50"),
            cost_per_kg=Decimal("20.00"),
        )
        db.session.add(self.ingredient)
        db.session.commit()

    def test_calculate_nutrition_zero_batch_size(self):
        """Test nutrition calculation with zero batch size."""
        result = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg=0,
            ingredients_with_percentages=[
                {"ingredient_id": self.ingredient.id, "percentage": 100},
            ]
        )
        
        # Should handle gracefully
        assert result["average_protein_percent"] == 0

    def test_calculate_nutrition_single_ingredient(self):
        """Test nutrition calculation with single ingredient at 100%."""
        result = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg=100,
            ingredients_with_percentages=[
                {"ingredient_id": self.ingredient.id, "percentage": 100},
            ]
        )
        
        # Should equal ingredient's protein content
        assert result["average_protein_percent"] == 10.0  # 100 g/kg = 10%

    def test_ingredients_percentages_over_100(self):
        """Test handling of ingredients that don't sum to 100%."""
        # Backend should normalize or calculate weighted average
        result = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg=500,
            ingredients_with_percentages=[
                {"ingredient_id": self.ingredient.id, "percentage": 150},  # Over 100%
            ]
        )
        
        # Should calculate based on the 150% (or normalize internally)
        assert result["total_protein_grams"] > 0
        assert result["average_protein_percent"] > 0

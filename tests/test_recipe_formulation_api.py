"""
Integration tests for Recipe Formulation API endpoints.
Tests the complete HTTP flow for protein targeting and recipe auto-save.
"""
from __future__ import annotations
import pytest
from decimal import Decimal
from tests.base import BaseTestCase
from app.models.supply import InventoryItem, FeedRecipe, FormulaIngredient
from app import db


class TestRecipeFormulationAPI(BaseTestCase):
    """Integration tests for recipe formulation endpoints."""

    def setUp(self):
        """Set up test ingredients and authentication."""
        super().setUp()
        self.auth_headers = self.get_auth_headers()
        
        # Create test ingredients with realistic protein values
        self.ingredients = {
            "maize_germ": InventoryItem(
                tenant_id=self.tenant_id,
                name="Maize Germ",
                protein_grams_per_kg=Decimal("120"),
                energy_mj_per_kg=Decimal("14.5"),
                fiber_grams_per_kg=Decimal("50"),
                cost_per_kg=Decimal("25.00"),
            ),
            "wheat_bran": InventoryItem(
                tenant_id=self.tenant_id,
                name="Wheat Bran",
                protein_grams_per_kg=Decimal("80"),
                energy_mj_per_kg=Decimal("12.0"),
                fiber_grams_per_kg=Decimal("100"),
                cost_per_kg=Decimal("15.00"),
            ),
            "sunflower_cake": InventoryItem(
                tenant_id=self.tenant_id,
                name="Sunflower Cake",
                protein_grams_per_kg=Decimal("200"),
                energy_mj_per_kg=Decimal("13.0"),
                fiber_grams_per_kg=Decimal("80"),
                cost_per_kg=Decimal("35.00"),
            ),
        }
        
        db.session.add_all(self.ingredients.values())
        db.session.commit()

    def test_calculate_recipe_nutrition_endpoint_success(self):
        """Test POST /api/v1/recipes/calculate-nutrition success."""
        payload = {
            "batch_size_kg": 500,
            "ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 50},
                {"ingredient_id": self.ingredients["wheat_bran"].id, "percentage": 30},
                {"ingredient_id": self.ingredients["sunflower_cake"].id, "percentage": 20},
            ]
        }
        
        response = self.client.post(
            "/api/v1/recipes/calculate-nutrition",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["batch_size_kg"] == 500
        assert data["average_protein_percent"] == 12.4
        assert data["total_protein_grams"] == 62000
        assert len(data["ingredients"]) == 3

    def test_calculate_recipe_nutrition_accepts_camel_case_ingredient_id(self):
        """Frontend payloads using ingredientId should be accepted."""
        payload = {
            "batch_size_kg": 500,
            "ingredients": [
                {"ingredientId": self.ingredients["maize_germ"].id, "percentage": 50},
                {"ingredientId": self.ingredients["wheat_bran"].id, "percentage": 30},
                {"ingredientId": self.ingredients["sunflower_cake"].id, "percentage": 20},
            ]
        }

        response = self.client.post(
            "/api/v1/recipes/calculate-nutrition",
            json=payload,
            headers=self.auth_headers,
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["average_protein_percent"] == 12.4

    def test_calculate_recipe_nutrition_missing_batch_size(self):
        """Test POST /api/v1/recipes/calculate-nutrition with missing batch_size."""
        payload = {
            "ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 100},
            ]
        }
        
        response = self.client.post(
            "/api/v1/recipes/calculate-nutrition",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 400
        assert "batch_size_kg" in response.get_json()["error"]

    def test_calculate_recipe_nutrition_no_ingredients(self):
        """Test POST /api/v1/recipes/calculate-nutrition with no ingredients."""
        payload = {
            "batch_size_kg": 500,
            "ingredients": []
        }
        
        response = self.client.post(
            "/api/v1/recipes/calculate-nutrition",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 400
        assert "ingredient" in response.get_json()["error"].lower()

    def test_formulate_recipe_endpoint_success(self):
        """Test POST /api/v1/recipes/formulate success."""
        payload = {
            "batch_size_kg": 500,
            "target_protein_percent": 16.5,
            "ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 50},
                {"ingredient_id": self.ingredients["wheat_bran"].id, "percentage": 30},
                {"ingredient_id": self.ingredients["sunflower_cake"].id, "percentage": 20},
            ]
        }
        
        response = self.client.post(
            "/api/v1/recipes/formulate",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["current_protein_percent"] == 12.4
        assert data["target_protein_percent"] == 16.5
        assert abs(data["adjustment_needed"] - 4.1) < 0.1
        assert len(data["adjusted_ingredients"]) == 3
        assert data["projected_nutrition"]["average_protein_percent"] >= 16.0

    def test_formulate_recipe_invalid_target_protein(self):
        """Test POST /api/v1/recipes/formulate with invalid target protein."""
        payload = {
            "batch_size_kg": 500,
            "target_protein_percent": 150,  # Invalid: > 100
            "ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 100},
            ]
        }
        
        response = self.client.post(
            "/api/v1/recipes/formulate",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 400

    def test_formulate_recipe_no_adjustment_needed(self):
        """Test POST /api/v1/recipes/formulate when target already achieved."""
        payload = {
            "batch_size_kg": 500,
            "target_protein_percent": 12.4,  # Already achieved
            "ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 50},
                {"ingredient_id": self.ingredients["wheat_bran"].id, "percentage": 30},
                {"ingredient_id": self.ingredients["sunflower_cake"].id, "percentage": 20},
            ]
        }
        
        response = self.client.post(
            "/api/v1/recipes/formulate",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["adjustment_needed"] == 0
        assert "No adjustment needed" in data["adjustment_strategy"]

    def test_auto_save_recipe_endpoint_success(self):
        """Test POST /api/v1/recipes/auto-save success."""
        payload = {
            "recipe_name": "Herd Target 4.3L - 16.5% Protein",
            "batch_size_kg": 500,
            "target_protein_percent": 16.5,
            "adjusted_ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 35},
                {"ingredient_id": self.ingredients["wheat_bran"].id, "percentage": 25},
                {"ingredient_id": self.ingredients["sunflower_cake"].id, "percentage": 40},
            ]
        }
        
        response = self.client.post(
            "/api/v1/recipes/auto-save",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "ADOPTED"
        assert data["recipe_name"] == "Herd Target 4.3L - 16.5% Protein"
        assert data["target_protein_percent"] == 16.5
        assert "formulated and adopted" in data["message"]
        assert data["recipe_id"] is not None
        
        # Verify recipe was persisted
        recipe = FeedRecipe.query.filter_by(id=data["recipe_id"]).first()
        assert recipe is not None
        assert recipe.is_active is True

    def test_auto_save_recipe_empty_name(self):
        """Test POST /api/v1/recipes/auto-save with empty recipe name."""
        payload = {
            "recipe_name": "",
            "batch_size_kg": 500,
            "target_protein_percent": 16.5,
            "adjusted_ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 100},
            ]
        }
        
        response = self.client.post(
            "/api/v1/recipes/auto-save",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 400
        assert "recipe_name" in response.get_json()["error"]

    def test_auto_save_recipe_invalid_ingredient(self):
        """Test POST /api/v1/recipes/auto-save with non-existent ingredient."""
        payload = {
            "recipe_name": "Test Recipe",
            "batch_size_kg": 500,
            "target_protein_percent": 16.5,
            "adjusted_ingredients": [
                {"ingredient_id": 9999, "percentage": 100},  # Non-existent
            ]
        }
        
        response = self.client.post(
            "/api/v1/recipes/auto-save",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 400
        assert "not found" in response.get_json()["error"].lower()

    def test_auto_save_recipe_with_yield_target_id(self):
        """Test POST /api/v1/recipes/auto-save with yield_target_id for Milk Lab integration."""
        payload = {
            "recipe_name": "Recipe from Milk Lab",
            "batch_size_kg": 500,
            "target_protein_percent": 16.5,
            "adjusted_ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 35},
                {"ingredient_id": self.ingredients["wheat_bran"].id, "percentage": 25},
                {"ingredient_id": self.ingredients["sunflower_cake"].id, "percentage": 40},
            ],
            "yield_target_id": 123
        }
        
        response = self.client.post(
            "/api/v1/recipes/auto-save",
            json=payload,
            headers=self.auth_headers,
        )
        
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "ADOPTED"

    def test_get_suggested_feed_mix_success(self):
        """Test GET /api/v1/feed-formulation/suggested-mix success."""
        # First, we need to set up yield targets (mocking Milk Lab state)
        from app.models.livestock import Cow, CowStatus
        
        # Create a lactating cow with yield target
        cow = Cow(
            tenant_id=self.tenant_id,
            tag_number="COW-001",
            name="Bessie",
            status=CowStatus.LACTATING,
        )
        db.session.add(cow)
        db.session.commit()
        
        # Create yield target
        from app.models.livestock import AnimalYieldTarget
        target = AnimalYieldTarget(
            tenant_id=self.tenant_id,
            animal_id=cow.id,
            target_liters=Decimal("20"),
            base_herd_feed_kg=Decimal("5"),
            times_to_feed_daily=3,
            is_active=True,
        )
        db.session.add(target)
        db.session.commit()
        
        # Now request suggested mix
        response = self.client.get(
            "/api/v1/feed-formulation/suggested-mix?batch_size_kg=500",
            headers=self.auth_headers,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["herd_total_target_liters"] == 20.0
        assert data["suggested_protein_percent"] == 16.5
        assert data["batch_size_kg"] == 500
        assert len(data["suggested_ingredients"]) > 0

    def test_get_suggested_feed_mix_no_yield_targets(self):
        """Test GET /api/v1/feed-formulation/suggested-mix with no yield targets."""
        response = self.client.get(
            "/api/v1/feed-formulation/suggested-mix?batch_size_kg=500",
            headers=self.auth_headers,
        )
        
        assert response.status_code == 400
        data = response.get_json()
        assert "No active yield targets" in data.get("message", data.get("error", ""))

    def test_complete_workflow_calculate_formulate_save(self):
        """Test complete workflow: calculate → formulate → save."""
        
        # Step 1: Calculate current nutrition
        calc_payload = {
            "batch_size_kg": 500,
            "ingredients": [
                {"ingredient_id": self.ingredients["maize_germ"].id, "percentage": 50},
                {"ingredient_id": self.ingredients["wheat_bran"].id, "percentage": 30},
                {"ingredient_id": self.ingredients["sunflower_cake"].id, "percentage": 20},
            ]
        }
        
        calc_response = self.client.post(
            "/api/v1/recipes/calculate-nutrition",
            json=calc_payload,
            headers=self.auth_headers,
        )
        assert calc_response.status_code == 200
        current_nutrition = calc_response.get_json()
        assert current_nutrition["average_protein_percent"] == 12.4
        
        # Step 2: Formulate with target
        formulate_payload = {
            **calc_payload,
            "target_protein_percent": 16.5
        }
        
        formulate_response = self.client.post(
            "/api/v1/recipes/formulate",
            json=formulate_payload,
            headers=self.auth_headers,
        )
        assert formulate_response.status_code == 200
        suggestions = formulate_response.get_json()
        assert suggestions["target_protein_percent"] == 16.5
        
        # Step 3: Save recipe with adjusted ingredients
        save_payload = {
            "recipe_name": "Complete Workflow Test Recipe",
            "batch_size_kg": 500,
            "target_protein_percent": 16.5,
            "adjusted_ingredients": [
                {
                    "ingredient_id": ing["ingredient_id"],
                    "percentage": ing["adjusted_percentage"]
                }
                for ing in suggestions["adjusted_ingredients"]
            ]
        }
        
        save_response = self.client.post(
            "/api/v1/recipes/auto-save",
            json=save_payload,
            headers=self.auth_headers,
        )
        assert save_response.status_code == 201
        saved_recipe = save_response.get_json()
        assert saved_recipe["status"] == "ADOPTED"
        assert saved_recipe["recipe_id"] is not None


class TestRecipeFormulationUnauthorized(BaseTestCase):
    """Test unauthorized access to recipe formulation endpoints."""

    def test_calculate_nutrition_without_auth(self):
        """Test endpoint without JWT token."""
        response = self.client.post(
            "/api/v1/recipes/calculate-nutrition",
            json={"batch_size_kg": 500, "ingredients": []}
        )
        assert response.status_code == 401

    def test_formulate_recipe_without_auth(self):
        """Test formulation without JWT token."""
        response = self.client.post(
            "/api/v1/recipes/formulate",
            json={"batch_size_kg": 500, "target_protein_percent": 16.5, "ingredients": []}
        )
        assert response.status_code == 401

    def test_auto_save_recipe_without_auth(self):
        """Test auto-save without JWT token."""
        response = self.client.post(
            "/api/v1/recipes/auto-save",
            json={"recipe_name": "Test", "batch_size_kg": 500, "target_protein_percent": 16.5}
        )
        assert response.status_code == 401

    def test_suggested_mix_without_auth(self):
        """Test suggested mix endpoint without JWT token."""
        response = self.client.get(
            "/api/v1/feed-formulation/suggested-mix"
        )
        assert response.status_code == 401

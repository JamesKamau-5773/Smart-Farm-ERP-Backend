import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from app import db
from app.models.livestock import Cow
from app.models.supply import BatchIngredient, FeedBatch, FeedRecipe, FeedBatchConsumptionEvent, FeedFormula, FormulaIngredient, Ingredient, InventoryItem, InventoryTransaction, MilkLog, RecipeIngredient
from app.models.user import Role
from app.services.feed_mixer_policy_service import FeedMixerPolicyService
from tests.base import BaseTestCase


class NutritionRouteTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)

    def _login(self, username='farmer', password='password'):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps({'username': username, 'password': password}),
            content_type='application/json',
        )

    def test_batch_creation_deducts_inventory_in_real_time(self):
        ingredient_1 = Ingredient(
            tenant_id=self.tenant.id,
            name='Maize Germ',
            current_cost_per_kg=Decimal('55.00'),
            stock_quantity=Decimal('200.000'),
        )
        ingredient_2 = Ingredient(
            tenant_id=self.tenant.id,
            name='Cotton Seed Cake',
            current_cost_per_kg=Decimal('70.00'),
            stock_quantity=Decimal('150.000'),
        )
        db.session.add_all([ingredient_1, ingredient_2])
        db.session.commit()

        payload = {
            'batchName': 'June Feed Mix A',
            'totalWeight': 100,
            'totalCost': 6200,
            'costPerKg': 62,
            'ingredients': [
                {'ingredientId': ingredient_1.id, 'weight': 60, 'percentage': 60},
                {'ingredientId': ingredient_2.id, 'weight': 40, 'percentage': 40},
            ],
        }

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        body = json.loads(response.data.decode())
        self.assertEqual(body['status'], 'ACTIVE')

        db.session.refresh(ingredient_1)
        db.session.refresh(ingredient_2)
        self.assertEqual(float(ingredient_1.stock_quantity), 140.0)
        self.assertEqual(float(ingredient_2.stock_quantity), 110.0)

    def test_batch_creation_rejects_percentages_that_do_not_match_weights(self):
        ingredient = Ingredient(
            tenant_id=self.tenant.id,
            name='Maize Germ',
            current_cost_per_kg=Decimal('55.00'),
            stock_quantity=Decimal('200.000'),
        )
        db.session.add(ingredient)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                json={
                    'batchName': 'Invalid Share Batch',
                    'totalWeight': 100,
                    'ingredients': [
                        {'ingredientId': ingredient.id, 'weight': 100, 'percentage': 60},
                    ],
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn('must match its weight share', response.get_json()['error'])
        self.assertIsNone(FeedBatch.query.filter_by(batch_name='Invalid Share Batch').first())

    def test_batch_creation_treats_string_false_template_flag_as_false(self):
        ingredient = Ingredient(
            tenant_id=self.tenant.id,
            name='Wheat Bran',
            current_cost_per_kg=Decimal('45.00'),
            stock_quantity=Decimal('120.000'),
        )
        db.session.add(ingredient)
        db.session.commit()

        payload = {
            'batchName': 'String False Flag Batch',
            'formulaId': None,
            'isSavedAsTemplate': 'false',
            'totalWeight': 20,
            'totalCost': 900,
            'costPerKg': 45,
            'ingredients': [
                {'ingredientId': ingredient.id, 'weight': 20, 'percentage': 100},
            ],
        }

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        body = json.loads(response.data.decode())
        self.assertIsNone(body['formulaId'])

        formulas = FeedFormula.query.filter_by(tenant_id=self.tenant.id, name='String False Flag Batch').all()
        self.assertEqual(len(formulas), 0)

    def test_batch_creation_accepts_empty_string_formula_id_as_null(self):
        ingredient = Ingredient(
            tenant_id=self.tenant.id,
            name='Sunflower Meal',
            current_cost_per_kg=Decimal('52.00'),
            stock_quantity=Decimal('80.000'),
        )
        db.session.add(ingredient)
        db.session.commit()

        payload = {
            'batchName': 'Empty Formula ID Batch',
            'formulaId': '',
            'isSavedAsTemplate': False,
            'totalWeight': 10,
            'totalCost': 520,
            'costPerKg': 52,
            'ingredients': [
                {'ingredientId': ingredient.id, 'weight': 10, 'percentage': 100},
            ],
        }

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        body = json.loads(response.data.decode())
        self.assertIsNone(body['formulaId'])

    def test_batch_creation_accepts_planner_recipe_id_in_formula_id(self):
        ingredient = Ingredient(
            tenant_id=self.tenant.id,
            name='Wheat Pollard',
            current_cost_per_kg=Decimal('50.00'),
            stock_quantity=Decimal('90.000'),
        )
        db.session.add(ingredient)
        db.session.flush()

        inventory_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Wheat Pollard',
            sku='wp-001',
            category='Feed',
            unit='KG',
            current_qty=Decimal('90.00'),
            minimum_threshold=Decimal('10.00'),
        )
        db.session.add(inventory_item)
        db.session.flush()

        recipe = FeedRecipe(
            tenant_id=self.tenant.id,
            recipe_name='Planner Main Mix',
            target_protein_percentage=Decimal('14.50'),
            recipe_type='main_meal',
            is_active=True,
        )
        db.session.add(recipe)
        db.session.flush()
        db.session.add(RecipeIngredient(
            tenant_id=self.tenant.id,
            recipe_id=recipe.id,
            inventory_item_id=inventory_item.id,
            inclusion_percentage=Decimal('100.00'),
        ))
        db.session.commit()

        payload = {
            'batchName': 'Planner Formula ID Batch',
            'formulaId': recipe.id,
            'isSavedAsTemplate': False,
            'totalWeight': 10,
            'totalCost': 500,
            'costPerKg': 50,
            'ingredients': [
                {'ingredientId': ingredient.id, 'weight': 10, 'percentage': 100},
            ],
        }

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        body = json.loads(response.data.decode())
        self.assertIsNone(body['formulaId'])
        self.assertEqual(body['plannerRecipeId'], recipe.id)
        self.assertIn('compatibility', body['warning'])

    def test_batch_creation_accepts_inventory_item_id_as_ingredient_id(self):
        inventory_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Cotton Seed Cake',
            sku='csc-001',
            category='Feed',
            unit='KG',
            current_qty=Decimal('120.00'),
            minimum_threshold=Decimal('10.00'),
            cost_per_kg=Decimal('65.00'),
            protein_grams_per_kg=Decimal('160.00'),
        )
        db.session.add(inventory_item)
        db.session.commit()

        payload = {
            'batchName': 'Inventory ID Ingredient Batch',
            'formulaId': None,
            'isSavedAsTemplate': False,
            'totalWeight': 20,
            'totalCost': 1300,
            'costPerKg': 65,
            'ingredients': [
                {'ingredientId': inventory_item.id, 'weight': 20, 'percentage': 100},
            ],
        }

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        body = json.loads(response.data.decode())
        self.assertEqual(len(body['inventory']), 1)
        self.assertEqual(body['inventory'][0]['ingredientName'], 'Cotton Seed Cake')
        self.assertEqual(body['totalWeight'], 20.0)
        self.assertEqual(body['proteinPercentage'], 16.0)
        self.assertEqual(body['totalProteinGrams'], 3200.0)
        db.session.refresh(inventory_item)
        self.assertEqual(inventory_item.current_qty, Decimal('100.00'))

        movement = InventoryTransaction.query.filter_by(item_id=inventory_item.id).one()
        self.assertEqual(movement.transaction_type, 'OUT')
        self.assertEqual(movement.quantity, Decimal('20.00'))
        self.assertEqual(movement.reason_code, 'FEED_BATCH_MIX')
        self.assertIn(f"feed batch #{body['batchId']}", movement.notes)

    def test_calculate_batch_nutrition_returns_size_and_total_protein(self):
        inventory_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Protein Summary Ingredient',
            sku='protein-summary-001',
            category='Feed',
            unit='KG',
            current_qty=Decimal('100.00'),
            minimum_threshold=Decimal('10.00'),
            protein_grams_per_kg=Decimal('160.00'),
            cost_per_kg=Decimal('50.00'),
        )
        db.session.add(inventory_item)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/recipes/calculate-nutrition',
                json={
                    'batch_size_kg': 50,
                    'ingredients': [
                        {'ingredient_id': inventory_item.id, 'percentage': 100},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['batch_size_kg'], 50.0)
        self.assertEqual(body['average_protein_percent'], 16.0)
        self.assertEqual(body['total_protein_grams'], 8000.0)

    def test_batch_creation_uses_inventory_cost_instead_of_client_cost(self):
        inventory_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Sunflower Cake',
            sku='sc-authoritative-cost',
            category='Feed',
            unit='KG',
            current_qty=Decimal('100.00'),
            minimum_threshold=Decimal('10.00'),
            cost_per_kg=Decimal('55.00'),
        )
        db.session.add(inventory_item)
        db.session.commit()

        payload = {
            'batchName': 'Authoritative Cost Batch',
            'formulaId': None,
            'isSavedAsTemplate': False,
            'totalWeight': 20,
            'totalCost': 0,
            'costPerKg': 0,
            'ingredients': [
                {
                    'ingredientId': inventory_item.id,
                    'weight': 20,
                    'percentage': 100,
                    'lockedCostPerKg': 0,
                },
            ],
        }

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        body = json.loads(response.data.decode())
        batch = db.session.get(FeedBatch, body['batchId'])
        batch_ingredient = BatchIngredient.query.filter_by(batch_id=batch.id).one()

        self.assertEqual(batch.total_cost, Decimal('1100.0000'))
        self.assertEqual(batch.cost_per_kg, Decimal('55.0000'))
        self.assertEqual(batch_ingredient.locked_cost_per_kg, Decimal('55.0000'))
        self.assertEqual(body['totalCost'], 1100.0)
        self.assertEqual(body['costPerKg'], 55.0)

        db.session.refresh(inventory_item)
        self.assertEqual(inventory_item.current_qty, Decimal('80.00'))

    def test_batch_creation_rejects_invalid_ingredient_id_with_400(self):
        payload = {
            'batchName': 'Invalid Ingredient ID Batch',
            'formulaId': None,
            'isSavedAsTemplate': False,
            'totalWeight': 10,
            'totalCost': 500,
            'costPerKg': 50,
            'ingredients': [
                {'ingredientId': '', 'weight': 10, 'percentage': 100},
            ],
        }

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.data.decode())
        self.assertIn('ingredientId must be a valid positive integer', body['error'])

    def test_batch_creation_rejects_duplicate_ingredients_before_database_flush(self):
        inventory_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Duplicate Bran',
            sku='duplicate-bran',
            category='Feed',
            unit='KG',
            current_qty=Decimal('100.00'),
            minimum_threshold=Decimal('10.00'),
            cost_per_kg=Decimal('30.00'),
        )
        db.session.add(inventory_item)
        db.session.commit()

        payload = {
            'batchName': 'Duplicate Ingredient Batch',
            'totalWeight': 20,
            'ingredients': [
                {'ingredientId': inventory_item.id, 'weight': 10, 'percentage': 50},
                {'ingredientId': inventory_item.id, 'weight': 10, 'percentage': 50},
            ],
        }

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/batches',
                data=json.dumps(payload),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.data.decode())
        self.assertEqual(body['error'], 'Ingredient Duplicate Bran appears more than once in this batch.')

    def test_existing_formula_can_create_multiple_batches_without_reinserting_template_rows(self):
        ingredient = Ingredient(
            tenant_id=self.tenant.id,
            name='Reusable Formula Bran',
            current_cost_per_kg=Decimal('30.00'),
            stock_quantity=Decimal('100.000'),
        )
        formula = FeedFormula(
            tenant_id=self.tenant.id,
            name='Reusable Formula',
            created_by=self.farmer.id,
        )
        db.session.add_all([ingredient, formula])
        db.session.flush()
        db.session.add(FormulaIngredient(
            tenant_id=self.tenant.id,
            formula_id=formula.id,
            ingredient_id=ingredient.id,
            default_weight=Decimal('10.000'),
        ))
        db.session.commit()

        self._login()
        responses = []
        with self.client:
            for batch_name in ('Reusable Batch One', 'Reusable Batch Two'):
                responses.append(self.client.post(
                    '/api/v1/nutrition/batches',
                    json={
                        'batchName': batch_name,
                        'formulaId': formula.id,
                        'isSavedAsTemplate': False,
                        'totalWeight': 10,
                        'ingredients': [{
                            'ingredientId': ingredient.id,
                            'weight': 10,
                            'percentage': 100,
                        }],
                    },
                ))

        self.assertEqual([response.status_code for response in responses], [201, 201])
        self.assertEqual(FeedBatch.query.filter_by(tenant_id=self.tenant.id).count(), 2)
        self.assertEqual(FormulaIngredient.query.filter_by(
            tenant_id=self.tenant.id,
            formula_id=formula.id,
        ).count(), 1)
        db.session.refresh(ingredient)
        self.assertEqual(ingredient.stock_quantity, Decimal('80.000'))

    def test_insufficient_stock_rejects_entire_batch_without_deducting_inventory(self):
        inventory_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Limited Premix',
            sku='limited-premix',
            category='Feed',
            unit='KG',
            current_qty=Decimal('1.00'),
            minimum_threshold=Decimal('1.00'),
            cost_per_kg=Decimal('350.00'),
        )
        db.session.add(inventory_item)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post('/api/v1/nutrition/batches', json={
                'batchName': 'Impossible Premix Batch',
                'totalWeight': 10,
                'ingredients': [{
                    'ingredientId': inventory_item.id,
                    'inventoryItemId': inventory_item.id,
                    'weight': 10,
                    'percentage': 100,
                }],
            })

        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body['code'], 'INSUFFICIENT_STOCK')
        self.assertEqual(body['shortages'][0]['shortfallKg'], 9.0)
        self.assertEqual(FeedBatch.query.filter_by(tenant_id=self.tenant.id).count(), 0)
        db.session.refresh(inventory_item)
        self.assertEqual(inventory_item.current_qty, Decimal('1.00'))

    def test_recipe_and_unit_conversion_conflicts_return_409(self):
        ingredient = InventoryItem(
            tenant_id=self.tenant.id,
            name='Maize Germ',
            sku='mg-001',
            category='Feed',
            unit='KG',
            current_qty=Decimal('200.000'),
            minimum_threshold=Decimal('10.000'),
            cost_per_kg=Decimal('55.00'),
        )
        db.session.add(ingredient)
        db.session.commit()

        self._login()
        with self.client:
            first_recipe = self.client.post(
                '/api/v1/nutrition/recipes',
                data=json.dumps({
                    'name': 'Winter Mix',
                    'target_protein_percentage': 18,
                    'ingredients': [{
                        'inventory_item_id': ingredient.id,
                        'inclusion_percentage': 100,
                    }],
                }),
                content_type='application/json',
            )
            self.assertEqual(first_recipe.status_code, 201)

            invalid_recipe = self.client.post(
                '/api/v1/nutrition/recipes',
                data=json.dumps({
                    'name': 'Winter Mix Copy',
                    'target_protein_percentage': 18,
                    'ingredients': [{
                        'inventory_item_id': 999999,
                        'inclusion_percentage': 100,
                    }],
                }),
                content_type='application/json',
            )

            first_unit = self.client.post(
                '/api/v1/nutrition/units/conversions',
                data=json.dumps({
                    'item_id': ingredient.id,
                    'unit_name': 'Bag',
                    'kg_equivalent': 50,
                }),
                content_type='application/json',
            )
            self.assertEqual(first_unit.status_code, 201)

            duplicate_unit = self.client.post(
                '/api/v1/nutrition/units/conversions',
                data=json.dumps({
                    'item_id': ingredient.id,
                    'unit_name': 'Bag',
                    'kg_equivalent': 50,
                }),
                content_type='application/json',
            )

        self.assertEqual(invalid_recipe.status_code, 404)
        self.assertEqual(duplicate_unit.status_code, 409)

    def test_mixer_ingredients_endpoint_returns_only_eligible_items(self):
        dairy_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Dairy Meal',
            sku='dm-100',
            category='Feed',
            unit='KG',
            current_qty=Decimal('120.00'),
            minimum_threshold=Decimal('15.00'),
            allowed_mixers='dairy_meal,main_meal',
            mixer_role='dairy_meal_product',
            inclusion_percentage_dairy_meal=Decimal('30.0'),
            inclusion_percentage_main_meal=Decimal('12.0'),
        )
        roughage_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Napier Grass',
            sku='np-100',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('90.00'),
            minimum_threshold=Decimal('10.00'),
            allowed_mixers='main_meal',
            mixer_role='roughage',
            inclusion_percentage_dairy_meal=Decimal('0.0'),
            inclusion_percentage_main_meal=Decimal('40.0'),
        )
        db.session.add_all([dairy_item, roughage_item])
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/mixers/dairy_meal/ingredients')

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        names = [row['name'] for row in payload['ingredients']]
        self.assertIn('Dairy Meal', names)
        self.assertNotIn('Napier Grass', names)
        dairy_payload = next(row for row in payload['ingredients'] if row['name'] == 'Dairy Meal')
        self.assertIn('cost_per_kg', dairy_payload)

    def test_formulate_recipe_rejects_cross_mixer_ingredient(self):
        roughage_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Hay',
            sku='hay-101',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('60.00'),
            minimum_threshold=Decimal('8.00'),
            allowed_mixers='main_meal',
            mixer_role='roughage',
        )
        db.session.add(roughage_item)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/recipes/formulate',
                data=json.dumps({
                    'batch_size_kg': 500,
                    'target_protein_percent': 16.5,
                    'recipe_type': 'dairy_meal',
                    'ingredients': [
                        {'ingredient_id': roughage_item.id, 'percentage': 100},
                    ],
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.data.decode())
        self.assertIn('not eligible for recipe_type', payload['error'])

    def test_recipe_type_is_inferred_from_dairy_meal_only_ingredients(self):
        dairy_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Maize Germ',
            sku='mg-infer-101',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('100.00'),
            minimum_threshold=Decimal('10.00'),
            allowed_mixers='dairy_meal',
            mixer_role='concentrate_component',
        )
        db.session.add(dairy_item)
        db.session.commit()

        inferred = FeedMixerPolicyService.infer_unique_recipe_type(
            tenant_id=self.tenant.id,
            ingredient_ids=[dairy_item.id],
        )

        self.assertEqual(inferred, 'dairy_meal')

    @patch('app.api.nutrition.RecipeFormulationService.suggest_ingredient_adjustments')
    def test_formulate_recipe_infers_dairy_meal_when_type_is_omitted(self, suggest_adjustments):
        suggest_adjustments.return_value = {
            'recipe_type': 'dairy_meal',
            'adjusted_ingredients': [],
        }
        dairy_item = InventoryItem(
            tenant_id=self.tenant.id,
            name='Dairy Premix',
            sku='premix-infer-101',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('100.00'),
            minimum_threshold=Decimal('10.00'),
            allowed_mixers='dairy_meal',
            mixer_role='premix',
        )
        db.session.add(dairy_item)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post('/api/v1/nutrition/recipes/formulate', json={
                'batch_size_kg': 90,
                'target_protein_percent': 16,
                'ingredients': [
                    {'ingredient_id': dairy_item.id, 'percentage': 100},
                ],
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(suggest_adjustments.call_args.kwargs['recipe_type'], 'dairy_meal')

    def test_feed_cost_efficiency_applies_three_day_biological_lag(self):
        cow = Cow(tag_number='COW-NUTRITION-01', date_of_birth=date(2022, 1, 1))
        db.session.add(cow)
        db.session.flush()

        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Lag Test Batch',
            total_weight=Decimal('100.000'),
            total_cost=Decimal('1200.00'),
            cost_per_kg=Decimal('12.00'),
            mixed_on=date(2026, 6, 11),
            depleted_on=date(2026, 6, 13),
            created_by=self.farmer.id,
            status='DEPLETED',
            posted_at=datetime(2026, 6, 11, 8, 0, 0),
        )
        db.session.add(batch)
        db.session.flush()

        # Should be excluded: before lag start (mixed_on + 3 days = June 14)
        log_before_lag = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            amount_liters=Decimal('80.00'),
            session='Morning',
            recorded_by=self.farmer.id,
            timestamp=datetime(2026, 6, 13, 6, 0, 0),
        )
        # Should be included: within lag-adjusted window [June 14, June 16]
        log_in_window = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            amount_liters=Decimal('100.00'),
            session='Evening',
            recorded_by=self.farmer.id,
            timestamp=datetime(2026, 6, 14, 18, 0, 0),
        )
        # Should be excluded: after lag-adjusted end (depleted_on + 3 days = June 16)
        log_after_window = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=cow.id,
            amount_liters=Decimal('90.00'),
            session='Morning',
            recorded_by=self.farmer.id,
            timestamp=datetime(2026, 6, 17, 6, 0, 0),
        )
        db.session.add_all([log_before_lag, log_in_window, log_after_window])
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/analytics/feed-cost-efficiency')

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.data.decode())
        self.assertTrue(body['rows'])

        row = next(r for r in body['rows'] if r['batchId'] == batch.id)
        self.assertEqual(row['lagWindowStart'], '2026-06-14')
        self.assertEqual(row['lagWindowEnd'], '2026-06-16')
        self.assertEqual(row['totalMilkLiters'], 100.0)
        self.assertEqual(row['costPerLiter'], 12.0)

    def test_batch_depletion_is_marked_from_consumption_events(self):
        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Consumption Batch',
            total_weight=Decimal('100.000'),
            total_cost=Decimal('5000.00'),
            cost_per_kg=Decimal('50.00'),
            mixed_on=date(2026, 6, 11),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime(2026, 6, 11, 9, 0, 0),
        )
        db.session.add(batch)
        db.session.commit()

        self._login()
        with self.client:
            first = self.client.post(
                f'/api/v1/nutrition/batches/{batch.id}/consumption-events',
                data=json.dumps({'consumedWeight': 60, 'consumedOn': '2026-06-12', 'feeding_group': 'lactating'}),
                content_type='application/json',
            )
            second = self.client.post(
                f'/api/v1/nutrition/batches/{batch.id}/consumption-events',
                data=json.dumps({'consumedWeight': 40, 'consumedOn': '2026-06-13', 'feeding_group': 'lactating'}),
                content_type='application/json',
            )

        self.assertEqual(first.status_code, 200)
        first_body = json.loads(first.data.decode())
        self.assertEqual(first_body['batchStatus'], 'ACTIVE')
        self.assertEqual(first_body['remainingWeight'], 40.0)

        self.assertEqual(second.status_code, 200)
        second_body = json.loads(second.data.decode())
        self.assertEqual(second_body['batchStatus'], 'DEPLETED')
        self.assertEqual(second_body['remainingWeight'], 0.0)
        self.assertEqual(second_body['depletedOn'], '2026-06-13')

    def test_feed_cost_efficiency_includes_consumption_progress(self):
        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Dashboard Consumption Batch',
            total_weight=Decimal('50.000'),
            total_cost=Decimal('2500.00'),
            cost_per_kg=Decimal('50.00'),
            mixed_on=date.today(),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime.now(),
        )
        db.session.add(batch)
        db.session.flush()
        db.session.add(FeedBatchConsumptionEvent(
            tenant_id=self.tenant.id,
            batch_id=batch.id,
            consumed_weight=Decimal('12.500'),
            consumed_on=date.today(),
            created_by=self.farmer.id,
        ))
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/analytics/feed-cost-efficiency')

        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.get_json()['rows'] if item['batchId'] == batch.id)
        self.assertEqual(row['totalConsumedWeight'], 12.5)
        self.assertEqual(row['remainingWeight'], 37.5)
        self.assertEqual(row['rateBasis'], 'recorded_events')

    def test_active_batch_without_consumption_has_no_depletion_forecast(self):
        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Untracked Consumption Batch',
            total_weight=Decimal('50.000'),
            total_cost=Decimal('2500.00'),
            cost_per_kg=Decimal('50.00'),
            mixed_on=date.today(),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime.now(),
        )
        db.session.add(batch)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/analytics/feed-cost-efficiency')

        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.get_json()['rows'] if item['batchId'] == batch.id)
        self.assertEqual(row['consumedWeight'], 0.0)
        self.assertEqual(row['remainingWeight'], 50.0)
        self.assertEqual(row['dailyFeedingRateKg'], 0.0)
        self.assertIsNone(row['daysUntilEmpty'])
        self.assertIsNone(row['rateBasis'])

    def test_consumption_rate_starts_with_first_recorded_feeding(self):
        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Delayed Tracking Batch',
            total_weight=Decimal('50.000'),
            total_cost=Decimal('2500.00'),
            cost_per_kg=Decimal('50.00'),
            mixed_on=date.today() - timedelta(days=9),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime.now(),
        )
        db.session.add(batch)
        db.session.flush()
        db.session.add(FeedBatchConsumptionEvent(
            tenant_id=self.tenant.id,
            batch_id=batch.id,
            consumed_weight=Decimal('10.000'),
            consumed_on=date.today(),
            created_by=self.farmer.id,
        ))
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/analytics/feed-cost-efficiency')

        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.get_json()['rows'] if item['batchId'] == batch.id)
        self.assertEqual(row['dailyFeedingRateKg'], 10.0)
        self.assertEqual(row['daysUntilEmpty'], 4.0)
        self.assertEqual(row['rateBasis'], 'recorded_events')

    def test_consumption_event_cannot_exceed_remaining_batch_weight(self):
        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Bounded Consumption Batch',
            total_weight=Decimal('50.000'),
            total_cost=Decimal('2500.00'),
            cost_per_kg=Decimal('50.00'),
            mixed_on=date.today(),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime.now(),
        )
        db.session.add(batch)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                f'/api/v1/nutrition/batches/{batch.id}/consumption-events',
                json={'consumedWeight': 51, 'feeding_group': 'lactating'},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn('remaining batch weight of 50', response.get_json()['error'])
        self.assertEqual(FeedBatchConsumptionEvent.query.filter_by(batch_id=batch.id).count(), 0)

    def test_feed_cost_efficiency_saleable_only_toggle(self):
        cow = Cow(tag_number='COW-NUTRITION-02', date_of_birth=date(2022, 1, 2))
        db.session.add(cow)
        db.session.flush()

        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Saleable Toggle Batch',
            total_weight=Decimal('100.000'),
            total_cost=Decimal('600.00'),
            cost_per_kg=Decimal('6.00'),
            mixed_on=date(2026, 6, 11),
            depleted_on=date(2026, 6, 12),
            created_by=self.farmer.id,
            status='DEPLETED',
            posted_at=datetime(2026, 6, 11, 8, 0, 0),
        )
        db.session.add(batch)
        db.session.flush()

        # Both are inside lag window [2026-06-14, 2026-06-15]
        db.session.add_all([
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                amount_liters=Decimal('50.00'),
                session='Morning',
                recorded_by=self.farmer.id,
                timestamp=datetime(2026, 6, 14, 7, 0, 0),
                is_saleable=True,
            ),
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                amount_liters=Decimal('30.00'),
                session='Evening',
                recorded_by=self.farmer.id,
                timestamp=datetime(2026, 6, 14, 17, 0, 0),
                is_saleable=False,
            ),
        ])
        db.session.commit()

        self._login()
        with self.client:
            response_all = self.client.get('/api/v1/nutrition/analytics/feed-cost-efficiency')
            response_saleable = self.client.get('/api/v1/nutrition/analytics/feed-cost-efficiency?saleable_only=true')

        self.assertEqual(response_all.status_code, 200)
        self.assertEqual(response_saleable.status_code, 200)

        body_all = json.loads(response_all.data.decode())
        body_saleable = json.loads(response_saleable.data.decode())
        row_all = next(r for r in body_all['rows'] if r['batchId'] == batch.id)
        row_saleable = next(r for r in body_saleable['rows'] if r['batchId'] == batch.id)

        self.assertEqual(row_all['totalMilkLiters'], 80.0)
        self.assertEqual(row_saleable['totalMilkLiters'], 50.0)
        self.assertEqual(row_all['costPerLiter'], 7.5)
        self.assertEqual(row_saleable['costPerLiter'], 12.0)

    def test_active_batch_roi_trend_weekly(self):
        cow = Cow(tag_number='COW-NUTRITION-03', date_of_birth=date(2022, 1, 3))
        db.session.add(cow)
        db.session.flush()

        # Same week (Mon 2026-06-08)
        batch_1 = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Weekly Active A',
            total_weight=Decimal('100.000'),
            total_cost=Decimal('1000.00'),
            cost_per_kg=Decimal('10.00'),
            mixed_on=date(2026, 6, 1),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime(2026, 6, 1, 8, 0, 0),
        )
        batch_2 = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Weekly Active B',
            total_weight=Decimal('120.000'),
            total_cost=Decimal('500.00'),
            cost_per_kg=Decimal('4.17'),
            mixed_on=date(2026, 6, 2),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime(2026, 6, 2, 8, 0, 0),
        )
        db.session.add_all([batch_1, batch_2])
        db.session.flush()

        # In lag window for active batches (from mixed_on + 3 onward)
        db.session.add_all([
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                amount_liters=Decimal('200.00'),
                session='Morning',
                recorded_by=self.farmer.id,
                timestamp=datetime(2026, 6, 6, 6, 0, 0),
                is_saleable=True,
            ),
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=cow.id,
                amount_liters=Decimal('100.00'),
                session='Evening',
                recorded_by=self.farmer.id,
                timestamp=datetime(2026, 6, 6, 18, 0, 0),
                is_saleable=True,
            ),
        ])
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/analytics/active-batch-roi-trend-weekly')

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.data.decode())
        self.assertTrue(body['rows'])

        row = next(r for r in body['rows'] if r['weekStart'] == '2026-06-01')
        self.assertEqual(row['activeBatches'], 2)
        self.assertEqual(row['totalFeedCost'], 1500.0)
        self.assertEqual(row['totalMilkLiters'], 600.0)
        self.assertEqual(row['feedCostPerLiter'], 2.5)
        self.assertEqual(row['roiLitersPerKes'], 0.4)

    def test_group_feeding_plan_includes_calves_dry_and_lactating(self):
        today = date.today()

        lactating = Cow(
            tenant_id=self.tenant.id,
            tag_number='GROUP-LACT-001',
            name='Lactating Cow',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=1400),
            last_calving_date=today - timedelta(days=90),
            due_date=None,
            status='Lactating',
            is_active=True,
        )
        dry = Cow(
            tenant_id=self.tenant.id,
            tag_number='GROUP-DRY-001',
            name='Dry Cow',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=1500),
            last_calving_date=today - timedelta(days=180),
            due_date=today + timedelta(days=30),
            status='Dry',
            is_active=True,
        )
        calf_0_3 = Cow(
            tenant_id=self.tenant.id,
            tag_number='GROUP-CALF-001',
            name='Calf 2 Months',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=60),
            is_active=True,
        )
        calf_3_6 = Cow(
            tenant_id=self.tenant.id,
            tag_number='GROUP-CALF-002',
            name='Calf 5 Months',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=150),
            is_active=True,
        )
        heifer = Cow(
            tenant_id=self.tenant.id,
            tag_number='GROUP-HEIFER-001',
            name='Heifer 18 Months',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=540),
            is_active=True,
        )

        db.session.add_all([lactating, dry, calf_0_3, calf_3_6, heifer])
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/herd/feeding-plan/by-group')

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        groups = {row['feeding_group']: row for row in payload['groups']}

        self.assertEqual(groups['lactating']['headcount'], 1)
        self.assertEqual(groups['dry']['headcount'], 1)
        self.assertEqual(groups['calf_0_3m']['headcount'], 1)
        self.assertEqual(groups['calf_3_6m']['headcount'], 1)
        self.assertEqual(groups['heifer']['headcount'], 1)
        self.assertEqual(payload['totals']['total_active_animals'], 5)

    def test_feeding_group_profile_override_changes_group_plan(self):
        today = date.today()
        dry = Cow(
            tenant_id=self.tenant.id,
            tag_number='GROUP-DRY-OVERRIDE-001',
            name='Dry Override Cow',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=1600),
            last_calving_date=today - timedelta(days=200),
            due_date=today + timedelta(days=25),
            status='Dry',
            is_active=True,
        )
        db.session.add(dry)
        db.session.commit()

        self._login()
        with self.client:
            save_profile = self.client.put(
                '/api/v1/nutrition/feeding-groups/profiles/dry',
                data=json.dumps({
                    'avg_body_weight_kg': 600,
                    'dmi_percent_bw': 3.0,
                    'target_protein_percent': 13.5,
                    'feeding_times_per_day': 3,
                }),
                content_type='application/json',
            )
            plan_response = self.client.get('/api/v1/nutrition/herd/feeding-plan/by-group')

        self.assertEqual(save_profile.status_code, 200)
        self.assertEqual(plan_response.status_code, 200)

        payload = json.loads(plan_response.data.decode())
        groups = {row['feeding_group']: row for row in payload['groups']}
        dry_row = groups['dry']

        self.assertEqual(dry_row['headcount'], 1)
        self.assertEqual(dry_row['profile_source'], 'custom')
        self.assertEqual(dry_row['feeding_times_per_day'], 3)
        self.assertEqual(dry_row['daily_feed_per_head_kg'], 18.0)
        self.assertEqual(dry_row['daily_group_feed_kg'], 18.0)
        self.assertEqual(dry_row['daily_group_protein_kg'], 2.43)

    def test_group_plan_scales_assigned_recipe_and_only_converts_calibrated_measures(self):
        today = date.today()
        dry_cows = [
            Cow(
                tenant_id=self.tenant.id,
                tag_number=f'GROUP-MEASURE-{index}',
                name=f'Dry Cow {index}',
                breed_status='Foundation',
                date_of_birth=today - timedelta(days=1500),
                last_calving_date=today - timedelta(days=200),
                status='Dry',
                is_active=True,
            )
            for index in range(2)
        ]
        hay = InventoryItem(
            tenant_id=self.tenant.id,
            name='Measured Hay',
            sku='measured-hay',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('100.00'),
            minimum_threshold=Decimal('10.00'),
            protein_grams_per_kg=Decimal('90.00'),
            allowed_mixers='main_meal',
            mixer_role='roughage',
            inclusion_percentage_main_meal=Decimal('60.0'),
        )
        bran = InventoryItem(
            tenant_id=self.tenant.id,
            name='Measured Bran',
            sku='measured-bran',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('100.00'),
            minimum_threshold=Decimal('10.00'),
            protein_grams_per_kg=Decimal('150.00'),
            allowed_mixers='main_meal',
            mixer_role='energy',
            inclusion_percentage_main_meal=Decimal('40.0'),
        )
        db.session.add_all([*dry_cows, hay, bran])
        db.session.flush()
        recipe = FeedRecipe(
            tenant_id=self.tenant.id,
            recipe_name='Dry Cow Total Ration',
            target_protein_percentage=Decimal('12.0'),
            recipe_type='main_meal',
            feeding_group='dry',
            quantity_basis='total_ration',
            bulk_density_kg_per_litre=Decimal('0.40'),
            bucket_volume_litres=Decimal('20.0'),
            scoop_weight_kg=Decimal('2.0'),
            is_active=True,
        )
        db.session.add(recipe)
        db.session.flush()
        db.session.add_all([
            RecipeIngredient(tenant_id=self.tenant.id, recipe_id=recipe.id, inventory_item_id=hay.id, inclusion_percentage=Decimal('60.0')),
            RecipeIngredient(tenant_id=self.tenant.id, recipe_id=recipe.id, inventory_item_id=bran.id, inclusion_percentage=Decimal('40.0')),
        ])
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/herd/feeding-plan/by-group')

        self.assertEqual(response.status_code, 200)
        groups = {row['feeding_group']: row for row in response.get_json()['groups']}
        dry_row = groups['dry']
        self.assertEqual(dry_row['quantity_basis'], 'total_ration')
        self.assertEqual(dry_row['daily_kg_per_head'], 9.6)
        self.assertEqual(dry_row['kg_per_head_per_feeding'], 4.8)
        self.assertEqual(dry_row['daily_group_batch_kg'], 19.2)
        self.assertEqual(dry_row['group_batch_per_feeding_kg'], 9.6)
        self.assertEqual(dry_row['assigned_recipe']['name'], 'Dry Cow Total Ration')
        self.assertEqual(dry_row['assigned_recipe']['ingredients'][0]['daily_group_kg'], 11.52)
        self.assertEqual(dry_row['physical_measures']['daily_group_buckets'], 2.4)
        self.assertEqual(dry_row['physical_measures']['kg_per_scoop'], 2.0)
        self.assertEqual(dry_row['physical_measures']['daily_group_scoops'], 9.6)

        calf_row = groups['calf_0_3m']
        self.assertIsNone(calf_row['assigned_recipe'])
        self.assertIsNone(calf_row['physical_measures'])

        recipe.quantity_basis = 'concentrate'
        recipe.concentrate_kg_per_head_day = None
        db.session.commit()
        with self.client:
            unconfigured_response = self.client.get('/api/v1/nutrition/herd/feeding-plan/by-group')

        unconfigured_dry = {row['feeding_group']: row for row in unconfigured_response.get_json()['groups']}['dry']
        self.assertTrue(unconfigured_dry['requires_concentrate_rate'])
        self.assertEqual(unconfigured_dry['daily_kg_per_head'], 0.0)
        self.assertEqual(unconfigured_dry['daily_group_batch_kg'], 0.0)
        self.assertEqual(unconfigured_dry['total_ration_kg_per_head_day'], 9.6)

    def test_create_recipe_with_feeding_group_defaults_recipe_type(self):
        ingredient = InventoryItem(
            tenant_id=self.tenant.id,
            name='Hay Bales',
            sku='hay-group-001',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('100.00'),
            minimum_threshold=Decimal('10.00'),
            protein_grams_per_kg=Decimal('90.00'),
            allowed_mixers='main_meal',
            mixer_role='roughage',
            inclusion_percentage_main_meal=Decimal('100.0'),
        )
        db.session.add(ingredient)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/recipes',
                data=json.dumps({
                    'name': 'Dry Cow Base Mix',
                    'feeding_group': 'dry',
                    'target_protein_percentage': 12.0,
                    'ingredients': [
                        {'inventory_item_id': ingredient.id, 'inclusion_percentage': 100},
                    ],
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        recipe = FeedRecipe.query.filter_by(tenant_id=self.tenant.id, recipe_name='Dry Cow Base Mix').first()
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.feeding_group, 'dry')
        self.assertEqual(recipe.recipe_type, 'main_meal')

    def test_auto_save_recipe_rejects_incompatible_feeding_group_and_recipe_type(self):
        ingredient = InventoryItem(
            tenant_id=self.tenant.id,
            name='Dairy Concentrate',
            sku='dcon-001',
            category='Feed',
            unit='KG',
            current_qty=Decimal('120.00'),
            minimum_threshold=Decimal('10.00'),
            protein_grams_per_kg=Decimal('180.00'),
            allowed_mixers='dairy_meal',
            mixer_role='concentrate_component',
            inclusion_percentage_dairy_meal=Decimal('100.0'),
        )
        db.session.add(ingredient)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                '/api/v1/recipes/auto-save',
                data=json.dumps({
                    'recipe_name': 'Invalid Dry Dairy Mix',
                    'feeding_group': 'dry',
                    'recipe_type': 'dairy_meal',
                    'batch_size_kg': 100,
                    'target_protein_percent': 14.0,
                    'adjusted_ingredients': [
                        {'ingredient_id': ingredient.id, 'percentage': 100},
                    ],
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.data.decode())
        self.assertIn('only supports recipe_type', payload['error'])

    def test_suggested_mix_by_group_uses_profile_target_and_group_recipe_type(self):
        today = date.today()
        calf = Cow(
            tenant_id=self.tenant.id,
            tag_number='CALF-GROUP-SUGGEST-001',
            name='Young Calf',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=50),
            is_active=True,
        )
        ingredient = InventoryItem(
            tenant_id=self.tenant.id,
            name='Calf Starter Premix',
            sku='calf-premix-001',
            category='Supplement',
            unit='KG',
            current_qty=Decimal('40.00'),
            minimum_threshold=Decimal('5.00'),
            protein_grams_per_kg=Decimal('220.00'),
            allowed_mixers='dairy_meal',
            mixer_role='premix',
            inclusion_percentage_dairy_meal=Decimal('12.0'),
        )
        db.session.add_all([calf, ingredient])
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get(
                '/api/v1/nutrition/feed-formulation/suggested-mix/by-group?feeding_group=calf_0_3m'
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['feeding_group'], 'calf_0_3m')
        self.assertEqual(payload['recipe_type'], 'dairy_meal')
        self.assertEqual(payload['headcount'], 1)
        self.assertEqual(payload['suggested_protein_percent'], 20.0)
        self.assertTrue(any(item['ingredient_id'] == ingredient.id for item in payload['suggested_ingredients']))

    def test_record_consumption_event_accepts_feeding_group(self):
        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Group Consumption Batch',
            total_weight=Decimal('50.000'),
            total_cost=Decimal('2500.00'),
            cost_per_kg=Decimal('50.00'),
            mixed_on=date.today(),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime.now(),
        )
        db.session.add(batch)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                f'/api/v1/nutrition/batches/{batch.id}/consumption-events',
                data=json.dumps({
                    'consumedWeight': 10,
                    'feeding_group': 'dry',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['feedingGroup'], 'dry')

        event = FeedBatchConsumptionEvent.query.filter_by(tenant_id=self.tenant.id, batch_id=batch.id).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.feeding_group, 'dry')

    def test_record_consumption_event_requires_feeding_group(self):
        batch = FeedBatch(
            tenant_id=self.tenant.id,
            batch_name='Uncategorized Consumption Batch',
            total_weight=Decimal('50.000'),
            total_cost=Decimal('2500.00'),
            cost_per_kg=Decimal('50.00'),
            mixed_on=date.today(),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime.now(),
        )
        db.session.add(batch)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                f'/api/v1/nutrition/batches/{batch.id}/consumption-events',
                json={'consumedWeight': 10},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn('feeding_group is required', response.get_json()['error'])
        self.assertEqual(FeedBatchConsumptionEvent.query.filter_by(batch_id=batch.id).count(), 0)

    def test_feed_cost_by_group_analytics_returns_group_totals(self):
        recipe = FeedRecipe(
            tenant_id=self.tenant.id,
            recipe_name='Calf Starter Recipe',
            target_protein_percentage=Decimal('20.00'),
            recipe_type='dairy_meal',
            feeding_group='calf_0_3m',
            is_active=True,
        )
        db.session.add(recipe)
        db.session.flush()

        batch = FeedBatch(
            tenant_id=self.tenant.id,
            recipe_id=recipe.id,
            batch_name='Calf Starter Batch',
            total_weight=Decimal('80.000'),
            total_cost=Decimal('4000.00'),
            cost_per_kg=Decimal('50.00'),
            mixed_on=date.today(),
            created_by=self.farmer.id,
            status='ACTIVE',
            posted_at=datetime.now(),
        )
        db.session.add(batch)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/analytics/feed-cost-by-group')

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['total_groups'], 1)
        self.assertEqual(payload['grand_total_feed_cost'], 4000.0)
        self.assertEqual(payload['rows'][0]['feeding_group'], 'calf_0_3m')
        self.assertEqual(payload['rows'][0]['batch_count'], 1)

    def test_group_planner_uses_authoritative_status_not_model_property(self):
        """Regression: planner must match herd-status service classification."""
        today = date.today()

        # Intentionally omit last_calving_date to mimic incomplete lifecycle
        # fields; explicit status should still classify these correctly.
        lactating_override = Cow(
            tenant_id=self.tenant.id,
            tag_number='AUTH-STATUS-LACT-001',
            name='Status Override Lactating',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=1300),
            status='Lactating',
            is_active=True,
        )
        dry_override = Cow(
            tenant_id=self.tenant.id,
            tag_number='AUTH-STATUS-DRY-001',
            name='Status Override Dry',
            breed_status='Foundation',
            date_of_birth=today - timedelta(days=1400),
            status='Dry',
            is_active=True,
        )

        db.session.add_all([lactating_override, dry_override])
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.get('/api/v1/nutrition/herd/feeding-plan/by-group')

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        groups = {row['feeding_group']: row for row in payload['groups']}

        self.assertEqual(groups['lactating']['headcount'], 1)
        self.assertEqual(groups['dry']['headcount'], 1)

import json
from datetime import date, datetime
from decimal import Decimal

from app import db
from app.models.livestock import Cow
from app.models.supply import FeedBatch, FeedRecipe, FeedBatchConsumptionEvent, FeedFormula, Ingredient, InventoryItem, MilkLog
from app.models.user import Role
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
                data=json.dumps({'consumedWeight': 60, 'consumedOn': '2026-06-12'}),
                content_type='application/json',
            )
            second = self.client.post(
                f'/api/v1/nutrition/batches/{batch.id}/consumption-events',
                data=json.dumps({'consumedWeight': 40, 'consumedOn': '2026-06-13'}),
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

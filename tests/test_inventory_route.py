import json
from decimal import Decimal

from tests.base import BaseTestCase
from app.models.user import Role
from app.repositories.supply_repo import InventoryRepository


class InventoryRouteTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)

    def _login(self, username, password):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password=password)),
            content_type='application/json',
        )

    def test_deduct_inventory_route(self):
        item = InventoryRepository.create_item(
            tenant_id=self.tenant.id,
            name='Dairy Concentrate',
            category='Feed',
            unit='kg',
            current_qty=Decimal('12.00'),
            minimum_threshold=Decimal('5.00'),
        )

        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/v1/inventory/deduct',
                data=json.dumps({
                    'item_id': item.id,
                    'quantity': 4.5,
                    'reference_note': 'Morning milking ration',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['unit'], 'kg')
        self.assertEqual(payload['new_balance'], 7.5)
        self.assertFalse(payload['reorder_alert'])

    def test_create_inventory_item_conflict_returns_409(self):
        self._login('farmer', 'password')

        with self.client:
            first = self.client.post(
                '/api/inventory/items',
                data=json.dumps({
                    'name': 'hay',
                    'sku': 'h-001',
                    'category': 'Bulk Feed',
                    'unit': 'KG',
                    'currentStock': 164,
                    'reorderLevel': 10,
                }),
                content_type='application/json',
            )
            self.assertEqual(first.status_code, 201)

            duplicate = self.client.post(
                '/api/inventory/items',
                data=json.dumps({
                    'name': 'hay',
                    'sku': 'h-001',
                    'category': 'Bulk Feed',
                    'unit': 'KG',
                    'currentStock': 164,
                    'reorderLevel': 10,
                }),
                content_type='application/json',
            )

        self.assertEqual(duplicate.status_code, 409)
        payload = json.loads(duplicate.data.decode())
        self.assertIn('already exists', payload['error'])

    def test_inventory_movement_prefers_transaction_type_when_alias_present(self):
        item = InventoryRepository.create_item(
            tenant_id=self.tenant.id,
            name='Hay Bales',
            category='Feed',
            unit='KG',
            current_qty=Decimal('0.00'),
            minimum_threshold=Decimal('5.00'),
        )

        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/inventory/movements',
                data=json.dumps({
                    'item_id': item.id,
                    'quantity': 50,
                    'transaction_type': 'IN',
                    'movement_type': 'restock',
                    'reference_note': 'UI restock flow',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['movement']['movement_type'], 'IN')
        self.assertEqual(payload['updatedItem']['currentStock'], 50.0)

    def test_inventory_item_update_persists_nutrition_fields(self):
        item = InventoryRepository.create_item(
            tenant_id=self.tenant.id,
            name='napier grass',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('70.00'),
            minimum_threshold=Decimal('10.00'),
        )

        self._login('farmer', 'password')
        with self.client:
            response = self.client.patch(
                f'/api/inventory/items/{item.id}',
                data=json.dumps({
                    'proteinGramsPerKg': 120,
                    'energyMjPerKg': 9.5,
                    'fiberGramsPerKg': 180,
                    'costPerKg': 25,
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['proteinGramsPerKg'], 120.0)
        self.assertEqual(payload['energyMjPerKg'], 9.5)
        self.assertEqual(payload['fiberGramsPerKg'], 180.0)
        self.assertEqual(payload['costPerKg'], 25.0)

    def test_inventory_create_autofills_standards_by_synonym(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/inventory/items',
                data=json.dumps({
                    'name': 'elephant grass',
                    'sku': 'np-002',
                    'category': 'Bulk Feed',
                    'unit': 'KG',
                    'currentStock': 25,
                    'reorderLevel': 5,
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertGreater(payload['proteinGramsPerKg'], 0)
        self.assertGreater(payload['energyMjPerKg'], 0)
        self.assertGreater(payload['fiberGramsPerKg'], 0)
        self.assertGreater(payload['costPerKg'], 0)
        self.assertIn('default_source', payload)
        self.assertEqual(payload['standards_version'], '2026.07')

    def test_inventory_create_keeps_user_overrides_over_standards(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/inventory/items',
                data=json.dumps({
                    'name': 'hay',
                    'sku': 'h-override',
                    'category': 'Bulk Feed',
                    'unit': 'KG',
                    'currentStock': 40,
                    'reorderLevel': 10,
                    'proteinGramsPerKg': 200,
                    'energyMjPerKg': 11,
                    'fiberGramsPerKg': 150,
                    'costPerKg': 44,
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['proteinGramsPerKg'], 200.0)
        self.assertEqual(payload['energyMjPerKg'], 11.0)
        self.assertEqual(payload['fiberGramsPerKg'], 150.0)
        self.assertEqual(payload['costPerKg'], 44.0)
        self.assertEqual(payload['default_source'], 'user_override')

    def test_inventory_bulk_feed_all_zero_rejected_with_field_errors(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/inventory/items',
                data=json.dumps({
                    'name': 'unknown roughage',
                    'sku': 'uf-001',
                    'category': 'Bulk Feed',
                    'unit': 'KG',
                    'currentStock': 10,
                    'reorderLevel': 2,
                    'proteinGramsPerKg': 0,
                    'energyMjPerKg': 0,
                    'fiberGramsPerKg': 0,
                    'costPerKg': 0,
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.data.decode())
        self.assertIn('field_errors', payload)
        self.assertGreaterEqual(len(payload['field_errors']), 4)

    def test_list_ingredient_standards_endpoint(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.get('/api/v1/nutrition/ingredient-standards')

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertIn('standards', payload)
        self.assertIn('category_baselines', payload)
        self.assertEqual(payload['standards_version'], '2026.07')

    def test_upsert_ingredient_standard(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/ingredient-standards',
                data=json.dumps({
                    'canonical_name': 'sunflower cake',
                    'synonyms': ['sunflower meal'],
                    'protein_grams_per_kg': 320,
                    'energy_mj_per_kg': 11.7,
                    'fiber_grams_per_kg': 140,
                    'cost_per_kg': 55,
                    'source_reference': 'Curated dry-matter reference',
                    'effective_date': '2026-07-03',
                    'updated_at': '2026-07-03T00:00:00Z',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['canonical_name'], 'sunflower cake')
        self.assertEqual(payload['standards_version'], '2026.07')

    def test_backfill_standards_endpoint_updates_only_bulk_feed_all_zero(self):
        self._login('farmer', 'password')
        zero_bulk = InventoryRepository.create_item(
            tenant_id=self.tenant.id,
            name='hay',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('12.00'),
            minimum_threshold=Decimal('2.00'),
            energy_mj_per_kg=Decimal('0'),
            protein_grams_per_kg=Decimal('0'),
            fiber_grams_per_kg=Decimal('0'),
            cost_per_kg=Decimal('0'),
        )
        non_bulk = InventoryRepository.create_item(
            tenant_id=self.tenant.id,
            name='chlorine',
            category='Chemical',
            unit='L',
            current_qty=Decimal('8.00'),
            minimum_threshold=Decimal('1.00'),
            energy_mj_per_kg=Decimal('0'),
            protein_grams_per_kg=Decimal('0'),
            fiber_grams_per_kg=Decimal('0'),
            cost_per_kg=Decimal('0'),
        )

        with self.client:
            response = self.client.post('/api/v1/nutrition/ingredient-standards/backfill', data=json.dumps({}), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['updated'], 1)

        refreshed_bulk = InventoryRepository.get_item(zero_bulk.id, tenant_id=self.tenant.id)
        refreshed_non_bulk = InventoryRepository.get_item(non_bulk.id, tenant_id=self.tenant.id)
        self.assertGreater(float(refreshed_bulk.protein_grams_per_kg), 0)
        self.assertEqual(float(refreshed_non_bulk.protein_grams_per_kg), 0)

    def test_backfill_standards_endpoint_dry_run_does_not_persist(self):
        self._login('farmer', 'password')
        zero_bulk = InventoryRepository.create_item(
            tenant_id=self.tenant.id,
            name='hay',
            category='Bulk Feed',
            unit='KG',
            current_qty=Decimal('12.00'),
            minimum_threshold=Decimal('2.00'),
            energy_mj_per_kg=Decimal('0'),
            protein_grams_per_kg=Decimal('0'),
            fiber_grams_per_kg=Decimal('0'),
            cost_per_kg=Decimal('0'),
        )

        with self.client:
            response = self.client.post(
                '/api/v1/nutrition/ingredient-standards/backfill',
                data=json.dumps({'dry_run': True}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertTrue(payload['dry_run'])
        self.assertEqual(payload['updated'], 1)

        refreshed_bulk = InventoryRepository.get_item(zero_bulk.id, tenant_id=self.tenant.id)
        self.assertEqual(float(refreshed_bulk.protein_grams_per_kg), 0)

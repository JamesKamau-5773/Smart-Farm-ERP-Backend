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

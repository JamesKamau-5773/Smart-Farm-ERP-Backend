from decimal import Decimal

from tests.base import BaseTestCase
from app.repositories.supply_repo import InventoryRepository


class InventoryTestCase(BaseTestCase):
    def test_inventory_master_and_ledger_flow(self):
        item = InventoryRepository.create_item(
            tenant_id=self.tenant.id,
            name='Unga Dairy Meal',
            category='Feed',
            unit='Bags (70kg)',
            current_qty=Decimal('10.00'),
            minimum_threshold=Decimal('3.00'),
        )

        storekeeper = self.create_user(username='storekeeper', password='password', role='FARMER')
        updated_item, is_low_stock = InventoryRepository.deduct_stock(
            item_id=item.id,
            amount=Decimal('2.50'),
            user_id=storekeeper.id,
            notes='Morning feeding deduction',
            tenant_id=self.tenant.id,
        )

        self.assertEqual(updated_item.current_qty, Decimal('7.50'))
        self.assertFalse(is_low_stock)

        _, transaction, is_low_stock = InventoryRepository.record_transaction(
            item_id=item.id,
            transaction_type='OUT',
            quantity=Decimal('5.00'),
            logged_by=storekeeper.id,
            notes='Afternoon ration',
            tenant_id=self.tenant.id,
        )

        self.assertEqual(transaction.transaction_type, 'OUT')
        self.assertTrue(is_low_stock)

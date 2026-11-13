"""Regression tests for issues found walking the feed-planning and inventory journeys."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from app import db
from app.models.supply import FeedRecipe, InventoryItem
from app.utils.farm_time import farm_today
from tests.base import BaseTestCase


def _item(tenant_id, name, *, protein, qty='1000', cost='30.00'):
    return InventoryItem(
        tenant_id=tenant_id,
        name=name,
        category='Bulk Feed',
        unit='kg',
        current_qty=Decimal(qty),
        minimum_threshold=Decimal('0'),
        protein_grams_per_kg=Decimal(protein),
        energy_mj_per_kg=Decimal('12'),
        fiber_grams_per_kg=Decimal('80'),
        cost_per_kg=Decimal(cost),
    )


class FeedPlanningFixesTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.headers = self.get_auth_headers()
        self.maize = _item(self.tenant_id, 'Maize Germ', protein='120')
        self.bran = _item(self.tenant_id, 'Wheat Bran', protein='160')
        # Entered as a percentage (30%) into the g/kg field.
        self.sunflower = _item(self.tenant_id, 'Sunflower Cake', protein='30')
        db.session.add_all([self.maize, self.bran, self.sunflower])
        db.session.commit()

    def _auto_save(self, **extra):
        payload = {
            'recipe_name': 'Heifer Mix',
            'batch_size_kg': 100,
            'target_protein_percent': 14,
            'adjusted_ingredients': [
                {'ingredient_id': self.maize.id, 'percentage': 60},
                {'ingredient_id': self.bran.id, 'percentage': 40},
            ],
            **extra,
        }
        return self.client.post('/api/v1/recipes/auto-save', json=payload, headers=self.headers)

    def test_saving_a_mix_succeeds_and_assigns_the_feeding_group(self):
        response = self._auto_save(feeding_group='heifer')
        self.assertEqual(response.status_code, 201, response.get_json())

        plan = self.client.get('/api/v1/nutrition/herd/feeding-plan/by-group', headers=self.headers).get_json()
        heifer = next(group for group in plan['groups'] if group['feeding_group'] == 'heifer')
        self.assertEqual(heifer['assigned_recipe']['name'], 'Heifer Mix')
        self.assertEqual(heifer['quantity_label'], 'Total ration (dry matter)')

    def test_saving_accepts_measurement_settings(self):
        response = self._auto_save(quantity_basis='concentrate', concentrate_kg_per_head_day=2.5)
        self.assertEqual(response.status_code, 201, response.get_json())
        recipe = db.session.get(FeedRecipe, response.get_json()['recipe_id'])
        self.assertEqual((recipe.quantity_basis, float(recipe.concentrate_kg_per_head_day)), ('concentrate', 2.5))

    def test_unassigned_groups_are_labelled_as_whole_diet_need(self):
        plan = self.client.get('/api/v1/nutrition/herd/feeding-plan/by-group', headers=self.headers).get_json()
        labels = {group['quantity_label'] for group in plan['groups']}
        self.assertEqual(labels, {'Total daily feed need (dry matter, all feeds)'})

    def test_suspicious_protein_is_flagged_on_inventory_and_mixer_payloads(self):
        items = self.client.get('/api/inventory/items', headers=self.headers).get_json()
        items = items if isinstance(items, list) else items.get('items', [])
        by_name = {item['name']: item for item in items}
        self.assertEqual(by_name['Maize Germ']['data_warnings'], [])
        [warning] = by_name['Sunflower Cake']['data_warnings']
        self.assertEqual((warning['code'], warning['suggested_value']), ('PROTEIN_LIKELY_PERCENT', 300.0))

        mixer = self.client.get('/api/v1/nutrition/mixers/main_meal/ingredients', headers=self.headers).get_json()
        flagged = [i['name'] for i in mixer['ingredients'] if i['data_warnings']]
        self.assertEqual(flagged, ['Sunflower Cake'])

    def test_infeasible_formulation_names_the_suspect_ingredient(self):
        response = self.client.post('/api/v1/recipes/formulate', json={
            'batch_size_kg': 100,
            'target_protein_percent': 40,
            'ingredients': [
                {'ingredient_id': self.maize.id, 'percentage': 50},
                {'ingredient_id': self.sunflower.id, 'percentage': 50},
            ],
        }, headers=self.headers)
        self.assertEqual(response.status_code, 422, response.get_json())
        [suspect] = response.get_json()['suspect_ingredients']
        self.assertEqual(suspect['name'], 'Sunflower Cake')

    def test_unexpected_errors_do_not_leak_internals(self):
        with mock.patch(
            'app.api.nutrition.RecipeFormulationService.save_recipe_from_formulation',
            side_effect=RuntimeError('psycopg password=secret'),
        ):
            response = self._auto_save()
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertEqual(body['code'], 'INTERNAL_ERROR')
        self.assertNotIn('details', body)
        self.assertNotIn('secret', response.get_data(as_text=True))

    def test_no_duplicate_feed_routes_are_registered(self):
        seen = {}
        for rule in self.app.url_map.iter_rules():
            if not any(part in rule.rule for part in ('nutrition', 'feed', 'recipe', 'yield-target', 'mixers')):
                continue
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                self.assertNotIn((rule.rule, method), seen, f'{method} {rule.rule} registered twice')
                seen[(rule.rule, method)] = rule.endpoint


class InventoryFixesTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.headers = self.get_auth_headers()
        self.item = _item(self.tenant_id, 'Maize Germ', protein='120', qty='100', cost='40.00')
        db.session.add(self.item)
        db.session.commit()

    def _restock(self, quantity, unit_cost=None):
        payload = {'item_id': self.item.id, 'quantity': quantity, 'transaction_type': 'IN', 'movement_type': 'restock'}
        if unit_cost is not None:
            payload['unit_cost'] = unit_cost
        return self.client.post('/api/inventory/movements', json=payload, headers=self.headers)

    def test_priced_delivery_updates_weighted_average_cost(self):
        response = self._restock(100, unit_cost=60)
        self.assertEqual(response.status_code, 201, response.get_json())
        db.session.refresh(self.item)
        self.assertEqual((self.item.current_qty, self.item.cost_per_kg), (Decimal('200.00'), Decimal('50.00')))

    def test_unpriced_delivery_keeps_cost(self):
        self.assertEqual(self._restock(23.5).status_code, 201)
        db.session.refresh(self.item)
        self.assertEqual((self.item.current_qty, self.item.cost_per_kg), (Decimal('123.50'), Decimal('40.00')))

    def test_delivery_into_empty_stock_takes_the_delivered_price(self):
        self.item.current_qty = Decimal('0')
        db.session.commit()
        self._restock(50, unit_cost=55)
        db.session.refresh(self.item)
        self.assertEqual(self.item.cost_per_kg, Decimal('55.00'))

    def test_negative_unit_cost_is_rejected(self):
        self.assertEqual(self._restock(10, unit_cost=-1).status_code, 400)

    def test_deleting_an_item_used_by_a_recipe_returns_409(self):
        saved = self.client.post('/api/v1/recipes/auto-save', json={
            'recipe_name': 'Maize Only', 'batch_size_kg': 50, 'target_protein_percent': 12,
            'adjusted_ingredients': [{'ingredient_id': self.item.id, 'percentage': 100}],
        }, headers=self.headers)
        self.assertEqual(saved.status_code, 201, saved.get_json())

        response = self.client.delete(f'/api/inventory/items/{self.item.id}', headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'ITEM_IN_USE')
        self.assertIsNotNone(db.session.get(InventoryItem, self.item.id))

    def test_unused_item_can_still_be_deleted(self):
        spare = _item(self.tenant_id, 'Spare Bran', protein='150')
        db.session.add(spare)
        db.session.commit()
        response = self.client.delete(f'/api/inventory/items/{spare.id}', headers=self.headers)
        self.assertEqual(response.status_code, 200)

    def test_impossible_nutrient_values_are_rejected(self):
        response = self.client.post('/api/inventory/items', json={
            'name': 'Typo Feed', 'category': 'Bulk Feed', 'unit': 'kg', 'currentStock': 10,
            'reorderLevel': 1, 'protein_grams_per_kg': 3000, 'cost_per_kg': 20,
        }, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Crude protein', response.get_json()['error'])


class FarmDateTestCase(BaseTestCase):
    def test_farm_today_follows_the_configured_time_zone(self):
        for zone in ('Pacific/Kiritimati', 'Etc/GMT+12', 'Africa/Nairobi'):
            self.app.config['FARM_TIMEZONE'] = zone
            self.assertEqual(farm_today(), datetime.now(timezone.utc).astimezone(ZoneInfo(zone)).date())

    def test_future_feeding_dates_are_rejected(self):
        headers = self.get_auth_headers()
        tomorrow = (farm_today() + timedelta(days=2)).isoformat()
        response = self.client.post('/api/v1/nutrition/batches/999/consumption-events', json={
            'consumedWeight': 1, 'consumedOn': tomorrow,
        }, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('future', response.get_json()['error'])


def test_weighted_average_cost_rule():
    from app.services.inventory_costing_service import InventoryCostingService

    cost = InventoryCostingService.weighted_average_cost
    assert cost(on_hand_qty=Decimal('100'), current_unit_cost=Decimal('40'),
                received_qty=Decimal('100'), received_unit_cost=Decimal('60')) == Decimal('50.00')
    assert cost(on_hand_qty=Decimal('0'), current_unit_cost=Decimal('40'),
                received_qty=Decimal('10'), received_unit_cost=Decimal('55')) == Decimal('55.00')
    # Negative on-hand (data drift) must not distort the price.
    assert cost(on_hand_qty=Decimal('-5'), current_unit_cost=Decimal('40'),
                received_qty=Decimal('10'), received_unit_cost=Decimal('55')) == Decimal('55.00')


class InventoryRecommendationsTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.headers = self.get_auth_headers()
        self.item = _item(self.tenant_id, 'Sunflower Cake', protein='30', qty='100', cost='50.00')
        db.session.add(self.item)
        db.session.commit()

    def _movement(self, **payload):
        return self.client.post('/api/inventory/movements', json={'item_id': self.item.id, **payload}, headers=self.headers)

    def test_archived_items_are_hidden_and_can_be_restored(self):
        self.assertEqual(self.client.post(f'/api/inventory/items/{self.item.id}/archive', headers=self.headers).status_code, 200)
        listed = self.client.get('/api/inventory/items', headers=self.headers).get_json()
        listed = listed if isinstance(listed, list) else listed.get('items', [])
        self.assertNotIn('Sunflower Cake', [i['name'] for i in listed])
        mixer = self.client.get('/api/v1/nutrition/mixers/main_meal/ingredients', headers=self.headers).get_json()
        self.assertNotIn('Sunflower Cake', [i['name'] for i in mixer['ingredients']])

        all_items = self.client.get('/api/inventory/items?include_archived=true', headers=self.headers).get_json()
        all_items = all_items if isinstance(all_items, list) else all_items.get('items', [])
        self.assertEqual([i['is_active'] for i in all_items if i['name'] == 'Sunflower Cake'], [False])

        self.client.post(f'/api/inventory/items/{self.item.id}/restore', headers=self.headers)
        db.session.refresh(self.item)
        self.assertTrue(self.item.is_active)

    def test_archived_items_cannot_join_new_mixes(self):
        self.client.post(f'/api/inventory/items/{self.item.id}/archive', headers=self.headers)
        response = self.client.post('/api/v1/recipes/auto-save', json={
            'recipe_name': 'Old Mix', 'batch_size_kg': 10, 'target_protein_percent': 14,
            'adjusted_ingredients': [{'ingredient_id': self.item.id, 'percentage': 100}],
        }, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_data_fix_applies_the_server_computed_correction(self):
        response = self.client.post(f'/api/inventory/items/{self.item.id}/data-fixes',
                                    json={'code': 'PROTEIN_LIKELY_PERCENT'}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['data_warnings'], [])
        db.session.refresh(self.item)
        self.assertEqual(self.item.protein_grams_per_kg, Decimal('300.00'))
        again = self.client.post(f'/api/inventory/items/{self.item.id}/data-fixes',
                                 json={'code': 'PROTEIN_LIKELY_PERCENT'}, headers=self.headers)
        self.assertEqual(again.status_code, 400)

    def test_priced_delivery_with_supplier_creates_lot_and_optional_expense(self):
        from app.models.finance import Transaction, TransactionCategory
        from app.models.supply import InventoryBatch

        no_expense = self._movement(quantity=50, transaction_type='IN', movement_type='restock',
                                    unit_cost=60, supplier_name='Unga Feeds')
        self.assertEqual(no_expense.status_code, 201, no_expense.get_json())
        self.assertIsNone(no_expense.get_json()['ledgerEntryId'])
        self.assertEqual(no_expense.get_json()['movement']['supplier_name'], 'Unga Feeds')

        with_expense = self._movement(quantity=50, transaction_type='IN', movement_type='restock',
                                      unit_cost=70, supplier_name='Unga Feeds', record_expense=True)
        body = with_expense.get_json()
        entry = db.session.get(Transaction, body['ledgerEntryId'])
        self.assertEqual((entry.category, entry.amount, entry.counterparty_name),
                         (TransactionCategory.FEED_PURCHASE, Decimal('3500.00'), 'Unga Feeds'))
        lot = InventoryBatch.query.one()  # same supplier and day share one lot
        self.assertEqual((lot.received_quantity_kg, lot.cost_per_kg), (Decimal('100.00'), Decimal('65.00')))

    def test_expense_requires_a_price(self):
        response = self._movement(quantity=5, transaction_type='IN', movement_type='restock', record_expense=True)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['code'], 'VALIDATION_ERROR')

    def test_write_off_is_posted_to_the_ledger(self):
        from app.models.finance import Transaction, TransactionCategory

        response = self._movement(quantity=10, transaction_type='SPOILAGE', notes='Got wet')
        self.assertEqual(response.status_code, 201, response.get_json())
        entry = db.session.get(Transaction, response.get_json()['ledgerEntryId'])
        self.assertEqual((entry.category, entry.amount), (TransactionCategory.INVENTORY_WRITE_OFF, Decimal('500.00')))

    def test_stock_count_loss_is_written_off(self):
        response = self.client.post(f'/api/inventory/items/{self.item.id}/audit', json={'physical_count': 90}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(self.item)
        self.assertEqual(self.item.current_qty, Decimal('90.00'))

    def test_stock_cannot_be_edited_directly(self):
        changed = self.client.patch(f'/api/inventory/items/{self.item.id}', json={'currentStock': 500}, headers=self.headers)
        self.assertEqual((changed.status_code, changed.get_json()['code']), (400, 'STOCK_CHANGE_REQUIRES_MOVEMENT'))
        unchanged = self.client.patch(f'/api/inventory/items/{self.item.id}',
                                      json={'currentStock': 100, 'name': 'Sunflower Cake (Grade A)'}, headers=self.headers)
        self.assertEqual(unchanged.status_code, 200, unchanged.get_json())

    def test_changes_are_audited(self):
        from app.models.audit import AuditLog

        self._movement(quantity=5, transaction_type='IN', movement_type='restock', unit_cost=55)
        self.client.patch(f'/api/inventory/items/{self.item.id}', json={'name': 'Sunflower Cake 36%'}, headers=self.headers)
        self.client.post(f'/api/inventory/items/{self.item.id}/archive', headers=self.headers)
        actions = [row.action for row in AuditLog.query.filter_by(entity_type='InventoryItem').order_by(AuditLog.id)]
        self.assertEqual(actions, ['INVENTORY_IN', 'INVENTORY_ITEM_UPDATE', 'INVENTORY_ITEM_ARCHIVE'])

    def test_plain_errors_get_a_code(self):
        response = self.client.get('/api/v1/nutrition/batches/999999/consumption-status', headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()['code'], 'NOT_FOUND')


class HeiferMixMixin:
    """An owner with a saved main-meal mix assigned to the heifer group."""
    def setUp(self):
        super().setUp()
        self.owner_headers = self.get_auth_headers()
        maize = _item(self.tenant_id, 'Maize Germ', protein='120')
        bran = _item(self.tenant_id, 'Wheat Bran', protein='160')
        db.session.add_all([maize, bran])
        db.session.commit()
        saved = self.client.post('/api/v1/recipes/auto-save', json={
            'recipe_name': 'Heifer Mix', 'batch_size_kg': 100, 'target_protein_percent': 14, 'feeding_group': 'heifer',
            'adjusted_ingredients': [{'ingredient_id': maize.id, 'percentage': 60}, {'ingredient_id': bran.id, 'percentage': 40}],
        }, headers=self.owner_headers)
        self.assertEqual(saved.status_code, 201, saved.get_json())


class DailyFeedingTestCase(HeiferMixMixin, BaseTestCase):
    def _staff_headers(self, page_access):
        from app.models.user import Role
        hand = self.create_user(username='hand', password='HandPass123', role=Role.FARM_HAND)
        hand.page_access = page_access
        db.session.commit()
        client = self.app.test_client()
        token = client.post('/api/auth/login', json={'username': 'hand', 'password': 'HandPass123'}).get_json()['access_token']
        return client, {'Authorization': f'Bearer {token}'}

    def test_feeding_page_sees_instructions_without_costs_or_recipes(self):
        client, headers = self._staff_headers(['production', 'feeding'])
        response = client.get('/api/v1/nutrition/feeding/today', headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        heifer = next(g for g in body['groups'] if g['feeding_group'] == 'heifer')
        self.assertEqual(heifer['mix_name'], 'Heifer Mix')
        text = response.get_data(as_text=True)
        for secret in ('cost', 'price', 'percentage', 'ingredients'):
            self.assertNotIn(secret, text)

        planning = client.get('/api/v1/nutrition/feeding-groups/profiles', headers=headers)
        self.assertEqual(planning.status_code, 403)

    def test_feed_planning_page_implies_daily_feeding(self):
        client, headers = self._staff_headers(['feed'])
        self.assertEqual(client.get('/api/v1/nutrition/feeding/today', headers=headers).status_code, 200)

    def test_new_farm_hands_default_to_daily_feeding_only(self):
        from app.services.page_access import ROLE_DEFAULT_PAGE_ACCESS
        self.assertIn('feeding', ROLE_DEFAULT_PAGE_ACCESS['FARM_HAND'])
        self.assertNotIn('feed', ROLE_DEFAULT_PAGE_ACCESS['FARM_HAND'])

    def test_suggested_batch_size_covers_demand_minus_store(self):
        response = self.client.get('/api/v1/nutrition/batches/suggested-size?recipe_type=main_meal&days=7',
                                   headers=self.owner_headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body['in_store_kg'], 0)
        if body['daily_demand_kg']:
            self.assertGreaterEqual(body['suggested_batch_kg'], body['daily_demand_kg'] * 7)
            self.assertEqual(body['suggested_batch_kg'] % 5, 0)
        else:
            self.assertEqual(body['suggested_batch_kg'], 0)
            self.assertTrue(body['reason'])

    def test_suggested_batch_size_validates_input(self):
        bad = self.client.get('/api/v1/nutrition/batches/suggested-size?recipe_type=main_meal&days=0', headers=self.owner_headers)
        self.assertEqual(bad.status_code, 400)


class FrontendFollowUpTestCase(HeiferMixMixin, BaseTestCase):
    def test_groups_say_why_they_are_not_ready(self):
        body = self.client.get('/api/v1/nutrition/feeding/today', headers=self.owner_headers).get_json()
        for group in body['groups']:
            self.assertIn('recipe_type', group)
            self.assertEqual(group['ready'], group['not_ready_reason'] is None)
            self.assertEqual(bool(group['not_ready_message']), group['not_ready_reason'] is not None)
        reasons = {g['feeding_group']: g['not_ready_reason'] for g in body['groups']}
        # The heifer mix exists but no animals are in the group and no batch has been mixed.
        self.assertIn(reasons['heifer'], {'NO_ANIMALS', 'NO_ACTIVE_BATCH'})
        self.assertTrue(all(reason == 'NO_MIX' for group, reason in reasons.items() if group != 'heifer'))

    def test_not_ready_reasons_are_checked_in_order(self):
        from app.services.feeding_instruction_service import FeedingInstructionService as service
        mix = {'assigned_recipe': {'id': 1}, 'headcount': 3}
        self.assertEqual(service._not_ready_reason({'headcount': 3}, 7), 'NO_MIX')
        self.assertEqual(service._not_ready_reason({**mix, 'headcount': 0}, 7), 'NO_ANIMALS')
        self.assertEqual(service._not_ready_reason({**mix, 'requires_concentrate_rate': True}, 7), 'NO_CONCENTRATE_RATE')
        self.assertEqual(service._not_ready_reason(mix, None), 'NO_ACTIVE_BATCH')
        self.assertIsNone(service._not_ready_reason(mix, 7))

    def test_suggested_size_reports_the_stock_limit(self):
        maize = InventoryItem.query.filter_by(tenant_id=self.tenant_id, name='Maize Germ').one()
        maize.current_qty = Decimal('30')  # 60% share -> 50 kg; bran 1000 kg at 40% -> 2500 kg
        db.session.commit()
        body = self.client.get('/api/v1/nutrition/batches/suggested-size?recipe_type=main_meal',
                               headers=self.owner_headers).get_json()
        self.assertEqual(body['max_batch_kg'], 50.0)
        self.assertEqual(body['limiting_ingredient']['name'], 'Maize Germ')
        self.assertIsNotNone(body['recipe_id'])

    def test_suggested_size_without_a_mix_has_no_stock_limit(self):
        body = self.client.get('/api/v1/nutrition/batches/suggested-size?recipe_type=dairy_meal',
                               headers=self.owner_headers).get_json()
        self.assertIsNone(body['max_batch_kg'])

    def test_write_offs_keep_their_reason(self):
        from app.models.supply import InventoryTransaction
        maize = InventoryItem.query.filter_by(tenant_id=self.tenant_id, name='Maize Germ').one()
        for reason in ('SPOILAGE', 'SPILL', 'EXPIRED', 'DAMAGE', 'SHRINKAGE'):
            response = self.client.post('/api/inventory/movements', json={
                'item_id': maize.id, 'quantity': 1, 'transaction_type': reason,
            }, headers=self.owner_headers)
            self.assertEqual(response.status_code, 201, response.get_json())
            self.assertIsNotNone(response.get_json()['ledgerEntryId'])
            self.assertEqual(db.session.get(InventoryTransaction, response.get_json()['movement']['id']).reason_code, reason)

    def test_farm_admin_can_count_stock(self):
        from app.models.user import Role
        maize = InventoryItem.query.filter_by(tenant_id=self.tenant_id, name='Maize Germ').one()
        self.create_user(username='farmadmin', password='AdminPass123', role=Role.FARM_ADMIN)
        client = self.app.test_client()
        token = client.post('/api/auth/login', json={'username': 'farmadmin', 'password': 'AdminPass123'}).get_json()['access_token']
        response = client.post(f'/api/inventory/items/{maize.id}/audit', json={'physical_count': 990},
                               headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_me_exposes_the_farm_time_zone(self):
        body = self.client.get('/api/auth/me', headers=self.owner_headers).get_json()
        self.assertEqual(body['farm_timezone'], 'Africa/Nairobi')

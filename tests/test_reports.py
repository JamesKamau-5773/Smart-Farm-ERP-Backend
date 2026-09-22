import json
from datetime import date, datetime, time, timedelta

from app import db
from app.models.farm import Farm
from app.models.finance import Buyer, CostClass, Customer, Delivery, SalesLedger, Transaction, TransactionCategory, TransactionStatus, TransactionType
from app.models.supply import MilkLog
from app.models.user import Role
from tests.base import BaseTestCase


class ReportsAPITestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        # Get auth headers for a user with FARMER role, which is allowed
        self.auth_headers = self.get_auth_headers(role=Role.FARMER)

    def _create_test_data(self):
        """Helper to create a known set of data for testing."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)

        # Day -2: 100L produced, 50L sold
        db.session.add(MilkLog(tenant_id=self.tenant.id, amount_liters=100, is_saleable=True, timestamp=datetime.combine(two_days_ago, time.min)))
        db.session.add(SalesLedger(tenant_id=self.tenant.id, date=two_days_ago, liters_sold=50, price_per_liter=1, total_amount=50))

        # Yesterday: 120L produced, 70L sold (2 sources)
        db.session.add(MilkLog(tenant_id=self.tenant.id, amount_liters=120, is_saleable=True, timestamp=datetime.combine(yesterday, time.min)))
        db.session.add(SalesLedger(tenant_id=self.tenant.id, date=yesterday, liters_sold=40, price_per_liter=1, total_amount=40))
        db.session.add(Delivery(tenant_id=self.tenant.id, date=yesterday, billable_liters=30, price_per_liter=1, total_price=30))

        # Today: 150L produced, 0 sold
        db.session.add(MilkLog(tenant_id=self.tenant.id, amount_liters=150, is_saleable=True, timestamp=datetime.combine(today, time.min)))

        # Data outside default range (35 days ago)
        old_date = today - timedelta(days=35)
        db.session.add(MilkLog(tenant_id=self.tenant.id, amount_liters=1000, is_saleable=True, timestamp=datetime.combine(old_date, time.min)))

        db.session.commit()

    def test_milk_inventory_report_default_date_range(self):
        """Test the milk inventory report with the default 30-day date range."""
        self._create_test_data()

        response = self.client.get('/api/reports/milk-inventory', headers=self.auth_headers)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode())

        # Check summary totals (should not include data from 35 days ago)
        summary = data['summary']
        self.assertAlmostEqual(summary['total_produced'], 100 + 120 + 150)
        self.assertAlmostEqual(summary['total_sold'], 50 + 70)
        self.assertAlmostEqual(summary['total_unsold'], (100 + 120 + 150) - (50 + 70))

        # Check daily records
        daily_records = data['daily_records']
        self.assertEqual(len(daily_records), 3)  # Today, yesterday, 2 days ago

        # Check today's record (first in the sorted list)
        today_record = daily_records[0]
        self.assertEqual(today_record['date'], date.today().isoformat())
        self.assertAlmostEqual(today_record['total_produced'], 150)
        self.assertAlmostEqual(today_record['total_sold'], 0)
        self.assertAlmostEqual(today_record['total_unsold'], 150)

        # Check yesterday's record
        yesterday_record = daily_records[1]
        self.assertEqual(yesterday_record['date'], (date.today() - timedelta(days=1)).isoformat())
        self.assertAlmostEqual(yesterday_record['total_produced'], 120)
        self.assertAlmostEqual(yesterday_record['total_sold'], 70)  # 40 + 30
        self.assertAlmostEqual(yesterday_record['total_unsold'], 50)

    def test_milk_inventory_report_custom_date_range(self):
        """Test the milk inventory report with custom start and end dates."""
        self._create_test_data()

        yesterday = date.today() - timedelta(days=1)
        two_days_ago = date.today() - timedelta(days=2)

        response = self.client.get(
            f'/api/reports/milk-inventory?start_date={two_days_ago.isoformat()}&end_date={yesterday.isoformat()}',
            headers=self.auth_headers
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode())

        # Summary should only include yesterday and the day before
        summary = data['summary']
        self.assertAlmostEqual(summary['total_produced'], 100 + 120)
        self.assertAlmostEqual(summary['total_sold'], 50 + 70)
        self.assertAlmostEqual(summary['total_unsold'], (100 + 120) - (50 + 70))

        # Should only be two records
        self.assertEqual(len(data['daily_records']), 2)
        self.assertEqual(data['daily_records'][0]['date'], yesterday.isoformat())
        self.assertEqual(data['daily_records'][1]['date'], two_days_ago.isoformat())

    def test_milk_inventory_report_no_data(self):
        """Test the report returns empty/zeroed data when no records exist."""
        response = self.client.get('/api/reports/milk-inventory', headers=self.auth_headers)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode())

        summary = data['summary']
        self.assertAlmostEqual(summary['total_produced'], 0)
        self.assertAlmostEqual(summary['total_sold'], 0)
        self.assertAlmostEqual(summary['total_unsold'], 0)
        self.assertEqual(len(data['daily_records']), 0)

    def test_milk_inventory_report_unauthorized_access(self):
        """Test that unauthenticated users cannot access the report."""
        response = self.client.get('/api/reports/milk-inventory')
        self.assertEqual(response.status_code, 401)  # Unauthorized

    def test_milk_inventory_report_insufficient_role(self):
        """Test that users with insufficient roles cannot access the report."""
        # FARM_HAND is not in the allowed list for this endpoint
        farm_hand_headers = self.get_auth_headers(role=Role.FARM_HAND)
        response = self.client.get('/api/reports/milk-inventory', headers=farm_hand_headers)
        self.assertEqual(response.status_code, 403)  # Forbidden

    def _create_dairy_unit_economics_test_data(self):
        today = date.today()
        db.session.add(Customer(
            tenant_id=self.tenant.id,
            name='Household A',
            phone_number='0700000001',
            status='Active',
            created_at=datetime.combine(today - timedelta(days=20), time.min),
        ))
        db.session.add(Buyer(
            tenant_id=self.tenant.id,
            name='Cafe B',
            phone_number='0700000002',
            is_active=True,
            created_at=datetime.combine(today - timedelta(days=10), time.min),
        ))
        db.session.add(Delivery(
            tenant_id=self.tenant.id,
            customer_id=1,
            date=today - timedelta(days=3),
            liters_delivered=60,
            personal_consumption_liters=0,
            billable_liters=60,
            price_per_liter=55,
            total_price=3300,
        ))
        db.session.add(SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=1,
            date=today - timedelta(days=2),
            liters_sold=140,
            price_per_liter=50,
            total_amount=7000,
        ))
        db.session.add_all([
            Transaction(
                tenant_id=self.tenant.id,
                farm_id=self.farm.id,
                transaction_type=TransactionType.EXPENSE,
                category=TransactionCategory.FEED_PURCHASE,
                cost_class=CostClass.COGS,
                amount=2000,
                status=TransactionStatus.POSTED.value,
                timestamp=datetime.combine(today - timedelta(days=2), time.min),
            ),
            Transaction(
                tenant_id=self.tenant.id,
                farm_id=self.farm.id,
                transaction_type=TransactionType.EXPENSE,
                category=TransactionCategory.OTHER,
                cost_class=CostClass.CUSTOMER_ACQUISITION,
                amount=1000,
                status=TransactionStatus.POSTED.value,
                timestamp=datetime.combine(today - timedelta(days=2), time.min),
            ),
        ])
        db.session.add(Farm(tenant_id=self.tenant.id, name='Second Farm'))
        db.session.commit()

    def test_dairy_unit_economics_report_with_overrides(self):
        self._create_dairy_unit_economics_test_data()

        response = self.client.get(
            '/api/reports/dairy-unit-economics?marketing_spend_kes=1000&new_customers_acquired=2&customer_lifespan_months=24',
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertIn('results', payload)
        self.assertIn('operational', payload)
        self.assertAlmostEqual(payload['inputs']['marketing_spend_kes'], 1000.0)
        self.assertEqual(payload['inputs']['new_customers_acquired'], 2)
        self.assertIsNotNone(payload['results']['cac_kes'])
        self.assertGreaterEqual(payload['operational']['liters_sold_total'], 200.0)
        self.assertAlmostEqual(payload['operational']['revenue_b2c_deliveries_kes'], 3300.0)
        self.assertAlmostEqual(payload['operational']['revenue_b2b_sales_kes'], 7000.0)
        self.assertEqual(payload['operational']['active_accounts_total'], 2)
        self.assertAlmostEqual(payload['operational']['production_cost_total_kes'], 2000.0)
        self.assertAlmostEqual(payload['operational']['production_cost_per_liter_kes'], 10.0)
        self.assertAlmostEqual(payload['operational']['realized_contribution_total_kes'], 8300.0)
        self.assertAlmostEqual(payload['results']['realized_ltv_kes'], 4150.0)
        self.assertAlmostEqual(payload['results']['ltv_kes'], 4150.0)
        self.assertNotEqual(payload['results']['forecast_ltv_kes'], payload['results']['realized_ltv_kes'])
        self.assertEqual(payload['data_quality']['cost_allocation_method'], 'classified_cogs_per_liter')
        self.assertEqual(len(payload['customer_economics']), 2)
        self.assertAlmostEqual(
            sum(account['allocated_production_cost_kes'] for account in payload['customer_economics']),
            2000.0,
        )
        self.assertAlmostEqual(
            sum(account['realized_ltv_kes'] for account in payload['customer_economics']),
            8300.0,
        )
        self.assertTrue(all(account['first_sale_date'] for account in payload['customer_economics']))
        self.assertTrue(all(account['last_sale_date'] for account in payload['customer_economics']))
        self.assertEqual(payload['receivables']['scope'], 'current_account_balances_not_period_revenue')
        self.assertEqual(payload['data_quality']['zero_price_delivery_count'], 0)

    def test_dairy_unit_economics_separates_revenue_from_receivables(self):
        self._create_dairy_unit_economics_test_data()
        customer = Customer.query.filter_by(tenant_id=self.tenant.id).one()
        customer.account_balance = 24780
        db.session.commit()

        response = self.client.get('/api/reports/dairy-unit-economics', headers=self.auth_headers)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertAlmostEqual(payload['operational']['revenue_total_kes'], 10300.0)
        self.assertAlmostEqual(payload['inputs']['marketing_spend_kes'], 1000.0)
        self.assertAlmostEqual(payload['results']['cac_kes'], 500.0)
        self.assertAlmostEqual(payload['results']['ltv_to_cac_ratio'], 8.3)
        self.assertAlmostEqual(payload['receivables']['current_net_balance_kes'], 24780.0)
        self.assertNotEqual(
            payload['operational']['revenue_total_kes'],
            payload['receivables']['current_net_balance_kes'],
        )

    def test_dairy_unit_economics_by_farm_report(self):
        self._create_dairy_unit_economics_test_data()

        response = self.client.get('/api/reports/dairy-unit-economics/by-farm', headers=self.auth_headers)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['farm_count'], 2)
        self.assertEqual(payload['attribution_mode'], 'tenant_scoped_mirrored_per_farm')
        self.assertEqual(len(payload['items']), 2)
        self.assertTrue(payload['items'][0]['attribution_limited'])

    def test_dairy_unit_economics_calculator_success(self):
        response = self.client.post(
            '/api/reports/dairy-unit-economics/calculator',
            headers=self.auth_headers,
            data=json.dumps({
                'sales_marketing_spend_kes': 1200,
                'new_customers_acquired': 3,
                'liters_purchased_per_month': 150,
                'gross_margin_per_liter_kes': 20,
                'customer_lifespan_months': 24,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertAlmostEqual(payload['results']['cac_kes'], 400.0)
        self.assertAlmostEqual(payload['results']['ltv_kes'], 72000.0)
        self.assertAlmostEqual(payload['results']['ltv_to_cac_ratio'], 180.0)

    def test_dairy_unit_economics_calculator_missing_fields(self):
        response = self.client.post(
            '/api/reports/dairy-unit-economics/calculator',
            headers=self.auth_headers,
            data=json.dumps({'sales_marketing_spend_kes': 1200}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    def test_dairy_unit_economics_report_unauthorized(self):
        response = self.client.get('/api/reports/dairy-unit-economics')
        self.assertEqual(response.status_code, 401)

    def test_dairy_unit_economics_report_insufficient_role(self):
        farm_hand_headers = self.get_auth_headers(role=Role.FARM_HAND)
        response = self.client.get('/api/reports/dairy-unit-economics', headers=farm_hand_headers)
        self.assertEqual(response.status_code, 403)

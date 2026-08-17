import json
from datetime import datetime, timezone
from unittest.mock import patch

from app import db
from app.models.finance import Delivery, SalesLedger
from app.models.supply import MilkLog
from tests.base import BaseTestCase


class DashboardAPITestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.auth_headers = self.get_auth_headers()

    def _setup_dashboard_data(self):
        """Helper to create a consistent set of data for dashboard tests."""
        today = datetime.now(timezone.utc).date()

        # 1. Setup Data
        # Production: 50L total, 45L saleable
        db.session.add(MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=25,
            is_saleable=True,
            timestamp=datetime.now(timezone.utc)
        ))
        db.session.add(MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=20,
            is_saleable=True,
            timestamp=datetime.now(timezone.utc)
        ))
        db.session.add(MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=5,
            is_saleable=False,  # Not for sale
            timestamp=datetime.now(timezone.utc)
        ))

        # Sales: 10L to buyer, 15.5L to customer = 25.5L total sold
        db.session.add(SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=self.buyer.id,
            date=today,
            liters_sold=10,
            price_per_liter=50,
            total_amount=500
        ))
        db.session.add(Delivery(
            tenant_id=self.tenant.id,
            customer_id=self.customer.id,
            date=today,
            billable_liters=15.5,
            price_per_liter=60,
            total_price=930
        ))
        db.session.commit()

    @patch('app.api.dashboard.FinanceService.get_daily_financial_summary')
    def test_get_production_summary_uses_finance_service_and_calculates_metrics(self, mock_get_summary):
        """
        Test that GET /api/production/summary correctly uses FinanceService for financial data
        and calculates its own operational metrics.
        """
        # 1. Mock the FinanceService to provide controlled financial data
        mock_get_summary.return_value = {
            'revenue_total_kes': 1234.56,
            'feed_cost_total_kes': 500.0,
            'net_margin_kes': 734.56,
            'other_expenses_kes': 0.0,
            'total_costs_kes': 500.0
        }

        # 2. Setup the operational data (milk logs, sales, etc.)
        self._setup_dashboard_data()

        # 3. Make API call
        response = self.client.get('/api/production/summary', headers=self.auth_headers)

        # 4. Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode())

        # Assert that financial data comes directly from the mocked service
        self.assertAlmostEqual(data['revenue_total_kes'], 1234.56)
        self.assertAlmostEqual(data['feed_cost_total_kes'], 500.0)
        self.assertAlmostEqual(data['net_margin_kes'], 734.56)

        # Assert that operational data is still calculated correctly by the endpoint itself
        self.assertIn('total_sold_liters', data)
        self.assertIn('remaining_milk_liters', data)
        self.assertAlmostEqual(data['production_total_liters'], 50.0)

        expected_saleable = 45.0
        expected_sold = 10.0 + 15.5  # 25.5
        expected_remaining = expected_saleable - expected_sold  # 19.5

        self.assertAlmostEqual(data['saleable_liters'], expected_saleable)
        self.assertAlmostEqual(data['total_sold_liters'], expected_sold)
        self.assertAlmostEqual(data['remaining_milk_liters'], expected_remaining)
        mock_get_summary.assert_called_once()

    def test_get_dashboard_alias_returns_production_summary(self):
        """
        Test that the alias GET /api/dashboard successfully returns the same data
        as /api/production/summary.
        """
        self._setup_dashboard_data()

        # Call the alias endpoint
        response = self.client.get('/api/dashboard', headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode())

        # Assert a few key values to confirm it's the right data
        self.assertIn('production_total_liters', data)
        self.assertAlmostEqual(data['production_total_liters'], 50.0)
        self.assertAlmostEqual(data['total_sold_liters'], 25.5)
        self.assertAlmostEqual(data['remaining_milk_liters'], 19.5)
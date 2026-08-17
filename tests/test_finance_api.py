import json
from datetime import datetime, timezone
from unittest.mock import patch

from app import db
from app.models.supply import MilkLog
from tests.base import BaseTestCase


class FinanceAPITestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.auth_headers = self.get_auth_headers()

    @patch('app.services.finance_service.FinanceService.get_daily_financial_summary')
    def test_get_unit_cost_correctly_calculates(self, mock_get_financial_summary):
        """
        Test that GET /api/unit-cost correctly calculates the unit cost
        by combining feed cost from FinanceService and milk production.
        """
        # 1. Mock the financial summary to control the feed cost input.
        # We simulate a daily feed cost of 500 KES.
        mock_get_financial_summary.return_value = {
            'feed_cost_total_kes': 500.0,
            'revenue_total_kes': 0, # Not relevant for this test
            'net_margin_kes': 0,    # Not relevant for this test
        }

        # 2. Create test data for milk production.
        # We simulate a total production of 100 liters for the day.
        db.session.add(MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=60,
            timestamp=datetime.now(timezone.utc)
        ))
        db.session.add(MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=40,
            timestamp=datetime.now(timezone.utc)
        ))
        db.session.commit()

        # 3. Make the API call to the endpoint under test.
        response = self.client.get('/api/unit-cost', headers=self.auth_headers)
        data = json.loads(response.data.decode())

        # 4. Assert the results.
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(data['total_feed_cost_kes'], 500.0)
        self.assertAlmostEqual(data['total_production_liters'], 100.0)
        # Expected unit cost = 500 (cost) / 100 (liters) = 5.0
        self.assertAlmostEqual(data['unit_cost_per_liter'], 5.0)
import json
from datetime import date, datetime, time, timedelta

from app import db
from app.models.finance import Delivery, SalesLedger
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
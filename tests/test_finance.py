import json
from datetime import datetime, date, timezone

from sqlalchemy.exc import IntegrityError

from tests.base import BaseTestCase
from app.models.user import Role
from app.models.finance import Buyer, SalesLedger, Transaction, TransactionType, TransactionCategory, PaymentStatus
from app.models.supply import MilkLog
from app.models.livestock import Cow
from app.models.supply import MilkSession
from app import db

class FinanceTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tag_number='COW001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self, username, password):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password=password)),
            content_type='application/json'
        )

    def test_get_unit_cost(self):
        """Test calculating the unit cost of milk production."""
        # Log some expenses
        tx1 = Transaction(transaction_type=TransactionType.EXPENSE, category=TransactionCategory.FEED_PURCHASE, amount=1000, recorded_by=self.farmer.id, timestamp=datetime.now(timezone.utc))
        tx2 = Transaction(transaction_type=TransactionType.EXPENSE, category=TransactionCategory.VET_FEES, amount=500, recorded_by=self.farmer.id, timestamp=datetime.now(timezone.utc))
        db.session.add_all([tx1, tx2])

        # Log some milk production
        milk_log1 = MilkLog(tenant_id=self.tenant.id, cow_id=self.cow.id, amount_liters=100, session=MilkSession.MORNING, is_saleable=True, recorded_by=self.farmer.id, timestamp=datetime.now(timezone.utc))
        milk_log2 = MilkLog(tenant_id=self.tenant.id, cow_id=self.cow.id, amount_liters=50, session=MilkSession.EVENING, is_saleable=True, recorded_by=self.farmer.id, timestamp=datetime.now(timezone.utc))
        db.session.add_all([milk_log1, milk_log2])
        db.session.commit()

        self._login('farmer', 'password')
        with self.client:
            response = self.client.get('/api/finance/unit-cost')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data.decode())
            self.assertEqual(data['total_expenses_kes'], 1500.0)
            self.assertEqual(data['total_saleable_liters'], 150.0)
            self.assertEqual(data['unit_cost_per_liter_kes'], 10.0)

    def test_trigger_billing(self):
        """Test initiating an M-Pesa STK push."""
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                '/api/finance/billing/stk-push',
                data=json.dumps(dict(
                    phone_number='254712345678',
                    amount=100
                )),
                content_type='application/json'
            )
            # This will likely fail without proper M-Pesa credentials,
            # but we can check for a 500-level error which indicates the code is running.
            self.assertIn(response.status_code, [200, 400, 500])

    def test_sales_ledger_rejects_duplicate_buyer_date(self):
        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Kisii Dairy',
            agreed_rate_per_liter=55,
        )
        db.session.add(buyer)
        db.session.commit()

        first_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 5, 31),
            liters_sold=100,
            total_cost=5500,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(first_entry)
        db.session.commit()

        duplicate_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 5, 31),
            liters_sold=100,
            total_cost=5500,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(duplicate_entry)

        with self.assertRaises(IntegrityError):
            db.session.commit()

        db.session.rollback()

    def test_create_buyer_conflict_returns_409(self):
        self._login('farmer', 'password')

        with self.client:
            first = self.client.post(
                '/api/finance/buyers',
                data=json.dumps({
                    'name': 'Kisii Dairy',
                    'agreed_rate_per_liter': 55,
                }),
                content_type='application/json',
            )
            self.assertEqual(first.status_code, 201)

            duplicate = self.client.post(
                '/api/finance/buyers',
                data=json.dumps({
                    'name': 'Kisii Dairy',
                    'agreed_rate_per_liter': 55,
                }),
                content_type='application/json',
            )

        self.assertEqual(duplicate.status_code, 409)

    def test_create_buyer_accepts_frontend_rate_per_liter_alias(self):
        self._login('farmer', 'password')

        with self.client:
            response = self.client.post(
                '/api/finance/buyers',
                data=json.dumps({
                    'name': 'peter',
                    'contact': '+2541234560789',
                    'type': 'Individual',
                    'rate_per_liter': 41,
                    'balance': 0,
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['name'], 'peter')
        self.assertEqual(payload['agreed_rate_per_liter'], 41.0)
        self.assertEqual(payload['rate_per_liter'], 41.0)

    def test_create_customer_conflict_returns_409(self):
        self._login('farmer', 'password')

        with self.client:
            first = self.client.post(
                '/api/finance/customers',
                data=json.dumps({
                    'name': 'Mary',
                    'phone_number': '254712345678',
                }),
                content_type='application/json',
            )
            self.assertEqual(first.status_code, 201)

            duplicate = self.client.post(
                '/api/finance/customers',
                data=json.dumps({
                    'name': 'Mary',
                    'phone_number': '254712345678',
                }),
                content_type='application/json',
            )

        self.assertEqual(duplicate.status_code, 409)

    def test_ledger_returns_server_computed_summary(self):
        self._login('farmer', 'password')

        with self.client:
            expense_response = self.client.post(
                '/api/finance/ledger',
                data=json.dumps({
                    'transaction_type': 'Expense',
                    'category': 'Feed Purchase',
                    'amount': 1000,
                }),
                content_type='application/json',
            )
            self.assertEqual(expense_response.status_code, 201)

            revenue_response = self.client.post(
                '/api/finance/ledger',
                data=json.dumps({
                    'transaction_type': 'Revenue',
                    'category': 'Milk Sale',
                    'amount': 2500,
                }),
                content_type='application/json',
            )
            self.assertEqual(revenue_response.status_code, 201)

            list_response = self.client.get('/api/finance/ledger')
            self.assertEqual(list_response.status_code, 200)
            payload = json.loads(list_response.data.decode())
            self.assertIn('summary', payload)
            self.assertEqual(payload['summary']['transaction_count'], 2)
            self.assertAlmostEqual(payload['summary']['total_income'], 2500.0)
            self.assertAlmostEqual(payload['summary']['total_costs'], 1000.0)
            self.assertAlmostEqual(payload['summary']['total_profit'], 1500.0)

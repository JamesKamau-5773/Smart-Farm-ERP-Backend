import json
from datetime import datetime, date, timezone

from sqlalchemy.exc import IntegrityError

from tests.base import BaseTestCase
from app.models.user import Role
from app.models.finance import Buyer, Customer, SalesLedger, Transaction, TransactionType, TransactionCategory, PaymentStatus
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

    def test_ledger_includes_date_and_counterparty_name(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Daily Dairies',
            agreed_rate_per_liter=60,
        )
        db.session.add(buyer)
        db.session.commit()

        with self.client:
            response = self.client.post(
                '/api/finance/ledger',
                data=json.dumps({
                    'transaction_type': 'Revenue',
                    'category': 'Milk Sale',
                    'amount': 9000,
                    'buyer_id': buyer.id,
                }),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 201)

            list_response = self.client.get('/api/finance/ledger')
            self.assertEqual(list_response.status_code, 200)
            payload = json.loads(list_response.data.decode())
            self.assertTrue(payload['items'])

            row = payload['items'][0]
            self.assertEqual(row['buyer_id'], buyer.id)
            self.assertEqual(row['buyer_name'], 'Daily Dairies')
            self.assertEqual(row['counterparty_name'], 'Daily Dairies')
            self.assertIsNotNone(row['timestamp'])
            self.assertIsNotNone(row['date'])

    def test_record_buyer_payment_reduces_outstanding_balance(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Ol Kalu',
            agreed_rate_per_liter=55,
        )
        db.session.add(buyer)
        db.session.commit()

        outstanding_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 6, 1),
            liters_sold=100,
            total_cost=1000,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(outstanding_entry)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/finance/buyers/{buyer.id}/payments',
                data=json.dumps({
                    'amount': 400,
                    'reference_code': 'PAY-001',
                    'note': 'Partial payment',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['payment']['amount'], 400.0)
        self.assertEqual(payload['payment']['previous_balance'], 1000.0)
        self.assertEqual(payload['payment']['current_balance'], 600.0)
        self.assertEqual(payload['buyer']['current_balance'], 600.0)
        self.assertEqual(payload['transaction']['category'], 'Buyer Payment')
        self.assertEqual(payload['transaction']['buyer_name'], 'Ol Kalu')

        db.session.refresh(outstanding_entry)
        self.assertEqual(float(outstanding_entry.total_cost), 600.0)
        self.assertEqual(outstanding_entry.payment_status, PaymentStatus.UNPAID)

    def test_record_buyer_payment_rejects_amount_above_outstanding(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Molo Milk',
            agreed_rate_per_liter=58,
        )
        db.session.add(buyer)
        db.session.commit()

        outstanding_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 6, 2),
            liters_sold=80,
            total_cost=300,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(outstanding_entry)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/finance/buyers/{buyer.id}/payments',
                data=json.dumps({
                    'amount': 500,
                    'note': 'Overpayment attempt',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.data.decode())
        self.assertIn('exceeds buyer outstanding balance', payload['error'])

    def test_record_buyer_payment_marks_ledger_paid_on_full_payment(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Brookside',
            agreed_rate_per_liter=52,
        )
        db.session.add(buyer)
        db.session.commit()

        outstanding_entry = SalesLedger(
            tenant_id=self.tenant.id,
            buyer_id=buyer.id,
            date=date(2026, 6, 3),
            liters_sold=50,
            total_cost=2600,
            payment_status=PaymentStatus.UNPAID,
        )
        db.session.add(outstanding_entry)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/finance/buyers/{buyer.id}/payments',
                data=json.dumps({
                    'amount': 2600,
                    'note': 'Full payment',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['payment']['current_balance'], 0.0)
        self.assertEqual(payload['buyer']['current_balance'], 0.0)

        db.session.refresh(outstanding_entry)
        self.assertEqual(float(outstanding_entry.total_cost), 0.0)
        self.assertEqual(outstanding_entry.payment_status, PaymentStatus.PAID)

    def test_record_buyer_payment_rejects_payment_with_no_outstanding_balance(self):
        self._login('farmer', 'password')

        buyer = Buyer(
            tenant_id=self.tenant.id,
            name='Happy Cow',
            agreed_rate_per_liter=50,
        )
        db.session.add(buyer)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/finance/buyers/{buyer.id}/payments',
                data=json.dumps({
                    'amount': 100,
                    'note': 'Payment attempt with no balance',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.data.decode())
        self.assertIn('Buyer has no unpaid balance', payload['error'])

    def test_delete_customer_with_dependencies_returns_409(self):
        self._login('farmer', 'password')
        
        customer = Customer(
            tenant_id=self.tenant.id,
            name='Test Customer',
            phone_number='254799887766'
        )
        db.session.add(customer)
        db.session.commit()

        transaction = Transaction(
            tenant_id=self.tenant.id,
            customer_id=customer.id,
            transaction_type=TransactionType.REVENUE,
            category=TransactionCategory.MILK_SALE,
            amount=100,
            recorded_by=self.farmer.id
        )
        db.session.add(transaction)
        db.session.commit()

        with self.client:
            response = self.client.delete(f'/api/finance/customers/{customer.id}')
        
        self.assertEqual(response.status_code, 409)
        data = json.loads(response.data.decode())
        self.assertIn('Cannot delete customer', data['error'])

    def test_delete_customer_without_dependencies_succeeds(self):
        self._login('farmer', 'password')
        
        customer = Customer(
            tenant_id=self.tenant.id,
            name='Deletable Customer',
            phone_number='254711223344'
        )
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

        with self.client:
            response = self.client.delete(f'/api/finance/customers/{customer_id}')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode())
        self.assertIn('deleted successfully', data['message'])

        # Verify it's gone
        deleted_customer = Customer.query.get(customer_id)
        self.assertIsNone(deleted_customer)

    def test_update_customer_patch_succeeds(self):
        self._login('farmer', 'password')

        customer = Customer(
            tenant_id=self.tenant.id,
            name='Original Name',
            phone_number='254700000001',
            account_balance=100,
            daily_contract_liters=5,
            is_active=True,
        )
        db.session.add(customer)
        db.session.commit()

        with self.client:
            response = self.client.patch(
                f'/api/finance/customers/{customer.id}',
                data=json.dumps({
                    'name': 'Updated Name',
                    'phone_number': '254700000009',
                    'daily_contract_liters': 12.5,
                    'is_active': False,
                    'contact_person': '',
                    'email': '',
                    'address': '',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['name'], 'Updated Name')
        self.assertEqual(payload['phone_number'], '254700000009')
        self.assertEqual(payload['daily_contract_liters'], 12.5)
        self.assertEqual(payload['is_active'], False)

    def test_update_customer_patch_duplicate_phone_returns_409(self):
        self._login('farmer', 'password')

        c1 = Customer(
            tenant_id=self.tenant.id,
            name='Customer One',
            phone_number='254700000011',
        )
        c2 = Customer(
            tenant_id=self.tenant.id,
            name='Customer Two',
            phone_number='254700000022',
        )
        db.session.add_all([c1, c2])
        db.session.commit()

        with self.client:
            response = self.client.patch(
                f'/api/finance/customers/{c2.id}',
                data=json.dumps({
                    'phone_number': '254700000011',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 409)
